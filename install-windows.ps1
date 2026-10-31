# SlothCAD installer for 64-bit Windows 10 / 11.
# Start it by double-clicking "Install SlothCAD.bat" (no administrator rights needed).
#
# What it does:
#   1. Finds Python 3.12 (or 3.11 / 3.13) and installs Python 3.12 for you if none is found.
#   2. Copies SlothCAD (these scripts and the "source" folder) to
#      %LOCALAPPDATA%\Programs\SlothCAD (a short path avoids Windows' 260-character
#      path limit inside the Python packages).
#   3. Creates a private Python environment there (next to "source") and installs
#      CadQuery, PySide6, ...
#   4. Adds Start menu and desktop shortcuts, opens .fcad files with SlothCAD,
#      and registers an uninstaller in Settings > Apps.
#   5. Runs a quick check (a few seconds). For the full test suite (several minutes)
#      use -FullTests or set SLOTHCAD_FULL_TESTS=1; SLOTHCAD_SKIP_TESTS=1 skips all checks.
#
# Re-running a newer installer updates SlothCAD in place; projects and settings are kept.

param([switch]$SkipTests, [switch]$FullTests, [switch]$NoDesktopShortcut)

# 'Continue': in Windows PowerShell 5.1 a program writing to stderr (pip warnings, the
# py launcher saying a version is missing) would otherwise abort the whole script.
# Program failures are checked through $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar
$PythonVersion = '3.12.10'
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path     # the folder with the scripts and "source"
$Target = Join-Path $env:LOCALAPPDATA 'Programs\SlothCAD'
$Code = Join-Path $Target 'source'                              # program files inside the install folder

function Say($text) { Write-Host $text -ForegroundColor Cyan }
function Fail($text) {
    Write-Host ''
    Write-Host $text -ForegroundColor Red
    exit 1
}

if (-not [Environment]::Is64BitOperatingSystem) { Fail 'SlothCAD needs 64-bit Windows.' }
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    Write-Host 'Windows on ARM: SlothCAD runs through x64 emulation; expect it to be slower.' -ForegroundColor Yellow
}

# Runs pip with its (very long, and silent while unpacking) output going to a log and
# shows one progress line instead: phase, bar, files written and elapsed time.
function Install-Packages($Requirements) {
    $log = Join-Path $env:TEMP 'slothcad-pip.log'
    $errLog = Join-Path $env:TEMP 'slothcad-pip-error.log'
    Remove-Item -ErrorAction SilentlyContinue $log, $errLog
    $site = Join-Path $Target '.venv\Lib\site-packages'
    $arguments = "-m pip install -r `"$Requirements`" --disable-pip-version-check --prefer-binary --no-input --progress-bar off"
    $process = Start-Process -FilePath $VenvPython -ArgumentList $arguments -NoNewWindow -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError $errLog
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $tick = 0; $written = 0L; $files = 0; $spinner = '|', '/', '-', '\'
    while (-not $process.HasExited) {
        $tick++
        $text = ''
        try {
            $stream = [IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
            $reader = New-Object IO.StreamReader($stream)
            $text = $reader.ReadToEnd(); $reader.Close()
        } catch { }
        if ($tick % 4 -eq 1) {   # walking ~40k files is the costly part; do it every ~2 s
            try {
                $written = 0L; $files = 0
                foreach ($f in ([IO.DirectoryInfo]$site).EnumerateFiles('*', 'AllDirectories')) { $written += $f.Length; $files++ }
            } catch { }
        }
        $wheelBytes = 0.0
        foreach ($m in [regex]::Matches($text, '(?m)^\s*(?:Using cached|Downloading) \S+\.whl \(([\d.]+) (kB|MB|GB)\)')) {
            $size = [double]$m.Groups[1].Value
            switch ($m.Groups[2].Value) { 'kB' { $size *= 1e3 } 'MB' { $size *= 1e6 } 'GB' { $size *= 1e9 } }
            $wheelBytes += $size
        }
        $unpacking = $text -match 'Installing collected packages'
        if ($unpacking -and $wheelBytes -gt 0) {
            $percent = [int][Math]::Max(1, [Math]::Min(99, 100 * $written / ($wheelBytes * 2.6)))
            $phase = 'Unpacking packages'
        } else {
            $collected = ([regex]::Matches($text, '(?m)^Collecting ')).Count
            $percent = [int][Math]::Min(30, $collected)
            $phase = "Resolving and fetching packages ($collected found)"
        }
        $width = 28; $filled = [int]($width * $percent / 100)
        $bar = ('#' * $filled) + ('-' * ($width - $filled))
        $line = "`r  [{0}] {1,3}%  {2}  {3:N0} files  {4:mm\:ss} {5}   " -f $bar, $percent, $phase, $files, $clock.Elapsed, $spinner[$tick % 4]
        Write-Host $line -NoNewline
        Start-Sleep -Milliseconds 500
    }
    $process.WaitForExit()
    Write-Host ("`r  [{0}] 100%  Done in {1:mm\:ss}                                                  " -f ('#' * 28), $clock.Elapsed)
    if ($process.ExitCode -ne 0) {
        Write-Host ''
        Write-Host 'The last lines of pip output:' -ForegroundColor Yellow
        if (Test-Path $log) { Get-Content $log -Tail 25 }
        if (Test-Path $errLog) { Get-Content $errLog -Tail 25 }
        return $false
    }
    return $true
}

# ---------------------------------------------------------------- Python ----
function Test-Python($exe) {
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return $false }
    if ($exe -like '*\WindowsApps\*') { return $false }   # Microsoft Store stub, not a real Python
    $version = & $exe -c "import sys,struct;print('%d.%d %d' % (sys.version_info[0],sys.version_info[1],struct.calcsize('P')*8))" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $version) { return $false }
    $parts = "$version".Trim().Split(' ')
    return (@('3.12','3.11','3.13') -contains $parts[0]) -and $parts[1] -eq '64'
}

function Find-Python {
    foreach ($minor in @('3.12','3.11','3.13')) {
        $digits = $minor.Replace('.','')
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python$digits\python.exe"),
            (Join-Path $env:ProgramFiles "Python$digits\python.exe")
        )
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $fromLauncher = & py "-$minor" -c "import sys;print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $fromLauncher) { $candidates = @("$fromLauncher".Trim()) + $candidates }
        }
        foreach ($exe in $candidates) { if (Test-Python $exe) { return $exe } }
    }
    return $null
}

function Install-Python {
    Say "Python 3.12 was not found. Installing Python $PythonVersion for your user account..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        $found = Find-Python
        if ($found) { return $found }
    }
    $installer = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
    Say "Downloading $url"
    # Windows PowerShell 5.1 may not offer TLS 1.2 by default; python.org requires it.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    try { Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing }
    catch { Fail "Could not download Python. Install Python 3.12 (64-bit) from https://www.python.org/downloads/windows/ and run this installer again." }
    $process = Start-Process -FilePath $installer -ArgumentList '/quiet','InstallAllUsers=0','InstallLauncherAllUsers=0','PrependPath=0','Include_launcher=1','Include_test=0' -Wait -PassThru
    Remove-Item $installer -ErrorAction SilentlyContinue
    if (@(0,3010) -notcontains $process.ExitCode) { Fail "The Python installer stopped with code $($process.ExitCode). Install Python 3.12 (64-bit) from python.org and run this installer again." }
    return Find-Python
}

Say 'Looking for Python...'
$Python = Find-Python
if (-not $Python) { $Python = Install-Python }
if (-not $Python) { Fail 'Python 3.12 (64-bit) is still not available. Install it from https://www.python.org/downloads/windows/ and run this installer again.' }
Say "Using $Python"

# ------------------------------------------------------------ App files ----
# Updating while SlothCAD runs would fail halfway (its files are locked), so check first.
$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target, [StringComparison]::OrdinalIgnoreCase) }
if ($running) { Fail 'SlothCAD is running. Close it, then run the installer again.' }

$sameFolder = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\') -eq $Target.TrimEnd('\')
if (-not $sameFolder) {
    Say "Copying SlothCAD to $Target"
    try {
        New-Item -ItemType Directory -Force -Path $Target -ErrorAction Stop | Out-Null
        # Remove the previous version's program files, but keep the Python environment
        # (much faster updates). Projects and settings are stored elsewhere.
        Get-ChildItem -Force -LiteralPath $Target | Where-Object { $_.Name -ne '.venv' } | Remove-Item -Recurse -Force -ErrorAction Stop
        Get-ChildItem -Force -LiteralPath $Source | Where-Object { @('.venv','.validation','__pycache__') -notcontains $_.Name } |
            Copy-Item -Destination $Target -Recurse -Force -ErrorAction Stop
        # Test logs and bytecode caches inside the source folder are not part of the program.
        # (Filtered by name explicitly: -Include is ignored together with -LiteralPath.)
        Get-ChildItem -Force -Recurse -Directory -LiteralPath $Code -ErrorAction SilentlyContinue |
            Where-Object { @('__pycache__','.validation') -contains $_.Name } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath (Join-Path $Code 'app.py'))) { throw "The program files were not copied: $Code\app.py is missing." }
    } catch {
        Fail "Could not update $Target. Close SlothCAD if it is running and run the installer again.`n$($_.Exception.Message)"
    }
}
Set-Location $Target

# ---------------------------------------------------- Python environment ----
$VenvPython = Join-Path $Target '.venv\Scripts\python.exe'
$VenvPythonW = Join-Path $Target '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython -c "import sys" 2>$null
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force (Join-Path $Target '.venv') }
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Say 'Creating the Python environment...'
    & $Python -m venv (Join-Path $Target '.venv')
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the Python environment.' }
}
Say 'Installing CadQuery, PySide6 and the other packages (this downloads about 400 MB the first time)...'
if (-not (Install-Packages (Join-Path $Code 'requirements.txt'))) {
    Fail 'Installing the Python packages failed. Check your internet connection and run the installer again. The messages above say which package failed.'
}

# CadQuery needs VTK and OCP's VTK bindings at import time. On Windows they fail to load
# when the Visual C++ runtime is missing, or when an older environment kept a mismatched
# pair; OCP then only says "cannot import name 'IVtkOCC_Shape'". Check, repair, check again.
$CheckOcc = Join-Path $Code 'check_occ.py'
& $VenvPython $CheckOcc 2>$null
if ($LASTEXITCODE -eq 2) {
    Say 'A system library (Microsoft Visual C++ Redistributable) is missing. Installing it; Windows may ask for permission...'
    $redist = Join-Path $env:TEMP 'vc_redist.x64.exe'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    try {
        Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile $redist -UseBasicParsing
        Start-Process -FilePath $redist -ArgumentList '/install','/passive','/norestart' -Wait | Out-Null
    } catch {
        Write-Host 'Could not install it automatically. Install it from https://aka.ms/vs/17/release/vc_redist.x64.exe' -ForegroundColor Yellow
    }
    Remove-Item $redist -ErrorAction SilentlyContinue
    & $VenvPython $CheckOcc 2>$null
}
if ($LASTEXITCODE -ne 0) {
    Say 'Reinstalling the OpenCascade and VTK packages...'
    $pins = @(Select-String -Path (Join-Path $Code 'requirements.txt') -Pattern '^(cadquery-ocp|vtk)==' | ForEach-Object { $_.Line.Trim() })
    & $VenvPython -m pip install --force-reinstall --no-deps --disable-pip-version-check --prefer-binary --no-input --progress-bar off @pins 2>$null | Out-Null
    & $VenvPython $CheckOcc
    if ($LASTEXITCODE -ne 0) {
        Fail ('SlothCAD''s 3D libraries (VTK / OpenCascade) do not load; the error is shown above.' +
              "`nInstall https://aka.ms/vs/17/release/vc_redist.x64.exe, restart Windows, delete $Target\.venv and run this installer again.")
    }
}

Say 'Preparing the fast viewport module...'
& $VenvPython (Join-Path $Code 'build_renderer.py')
if ($LASTEXITCODE -ne 0) { Write-Host 'The fast viewport module is not available; SlothCAD uses its built-in renderer instead.' -ForegroundColor Yellow }

# ------------------------------------------------- Shortcuts and files ----
$Icon = Join-Path $Code 'assets\slothcad.ico'
$Launcher = Join-Path $Target 'slothcad_launcher.pyw'   # stays next to the scripts
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $VenvPythonW
    $link.Arguments = "-X utf8 `"$Launcher`""
    $link.WorkingDirectory = $Target
    $link.IconLocation = "$Icon,0"
    $link.Description = 'SlothCAD - sketch and solid modelling'
    $link.Save()
}
Say 'Adding shortcuts...'
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Programs')) 'SlothCAD.lnk')
if (-not $NoDesktopShortcut) { New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'SlothCAD.lnk') }

# Double-clicking a .fcad project opens it in SlothCAD (current user only).
$classes = 'HKCU:\Software\Classes'
New-Item -Force -Path "$classes\.fcad" -Value 'SlothCAD.Project' | Out-Null
New-Item -Force -Path "$classes\SlothCAD.Project" -Value 'SlothCAD project' | Out-Null
New-Item -Force -Path "$classes\SlothCAD.Project\DefaultIcon" -Value "`"$Icon`",0" | Out-Null
New-Item -Force -Path "$classes\SlothCAD.Project\shell\open\command" -Value "`"$VenvPythonW`" -X utf8 `"$Launcher`" `"%1`"" | Out-Null

# Settings > Apps lists SlothCAD with an Uninstall button.
$version = (Select-String -Path (Join-Path $Code 'app.py') -Pattern "^VERSION='([^']+)'").Matches[0].Groups[1].Value
$uninstall = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SlothCAD'
New-Item -Force -Path $uninstall | Out-Null
$entries = @{
    DisplayName = 'SlothCAD'; DisplayVersion = $version; Publisher = 'SlothCAD'
    DisplayIcon = $Icon; InstallLocation = $Target
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Target\uninstall-windows.ps1`""
}
foreach ($key in $entries.Keys) { Set-ItemProperty -Path $uninstall -Name $key -Value $entries[$key] }
Set-ItemProperty -Path $uninstall -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $uninstall -Name NoRepair -Value 1 -Type DWord

# ------------------------------------------------------------------ Tests ----
if ($SkipTests -or $env:SLOTHCAD_SKIP_TESTS -eq '1') {
    Say 'Skipping the checks.'
} elseif ($FullTests -or $env:SLOTHCAD_FULL_TESTS -eq '1') {
    Say 'Running the full self-tests. This takes a few minutes; SlothCAD is already installed.'
    Push-Location $Code      # the runner writes its logs to .validation in the current folder
    & $VenvPython (Join-Path $Code 'validation_runner.py')
    $testExit = $LASTEXITCODE
    Pop-Location
    if ($testExit -ne 0) {
        Write-Host ''
        Write-Host "Warning: some self-tests failed. SlothCAD is installed; the logs are in $Code\.validation" -ForegroundColor Yellow
    }
} else {
    Say 'Running a quick check...'
    & $VenvPython (Join-Path $Code 'smoke_test.py')
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'Warning: the quick check failed. See the messages above. Run validation_runner.py for details.' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host "SlothCAD $version is installed." -ForegroundColor Green
Write-Host 'Start it from the Start menu or the desktop shortcut.'
Write-Host "You can delete the folder you downloaded; SlothCAD now lives in $Target"
