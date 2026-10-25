# Installs the portable SlothCAD package for the current user, without internet and without administrator rights.
# Copies this folder to %LOCALAPPDATA%\Programs\SlothCAD, adds shortcuts and the .fcad association, and an uninstaller.
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $env:LOCALAPPDATA 'Programs\SlothCAD'
if (-not (Test-Path (Join-Path $Here 'python\pythonw.exe'))) { Write-Host 'Run this from the extracted SlothCAD-Portable folder.' -ForegroundColor Red; exit 1 }
$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target, [StringComparison]::OrdinalIgnoreCase) }
if ($running) { Write-Host 'Close SlothCAD first, then install again.' -ForegroundColor Red; exit 1 }
Write-Host 'Copying SlothCAD...' -ForegroundColor Cyan
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
# The installed copy keeps its settings in the usual user folders: no portable.flag, no data folder.
robocopy $Here $Target /E /NFL /NDL /NJH /NJS /NP /XF portable.flag /XD data | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host 'Copying failed.' -ForegroundColor Red; exit 1 }
$Python = Join-Path $Target 'python\pythonw.exe'
$Launcher = Join-Path $Target 'slothcad_launcher.pyw'
$Icon = Join-Path $Target 'source\assets\slothcad.ico'
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $Python; $link.Arguments = "-X utf8 `"$Launcher`""
    $link.WorkingDirectory = $Target; $link.IconLocation = "$Icon,0"
    $link.Description = 'SlothCAD - sketch and solid modelling'; $link.Save()
}
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Programs')) 'SlothCAD.lnk')
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'SlothCAD.lnk')
$classes = 'HKCU:\Software\Classes'
New-Item -Force -Path "$classes\.fcad" -Value 'SlothCAD.Project' | Out-Null
New-Item -Force -Path "$classes\SlothCAD.Project" -Value 'SlothCAD project' | Out-Null
New-Item -Force -Path "$classes\SlothCAD.Project\DefaultIcon" -Value "`"$Icon`",0" | Out-Null
New-Item -Force -Path "$classes\SlothCAD.Project\shell\open\command" -Value "`"$Python`" -X utf8 `"$Launcher`" `"%1`"" | Out-Null
$version = (Select-String -Path (Join-Path $Target 'source\app.py') -Pattern "^VERSION='([^']+)'").Matches[0].Groups[1].Value
$uninstall = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SlothCAD'
New-Item -Force -Path $uninstall | Out-Null
$entries = @{ DisplayName = 'SlothCAD'; DisplayVersion = $version; Publisher = 'SlothCAD'; DisplayIcon = $Icon; InstallLocation = $Target
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Target\uninstall-windows.ps1`"" }
foreach ($key in $entries.Keys) { Set-ItemProperty -Path $uninstall -Name $key -Value $entries[$key] }
Set-ItemProperty -Path $uninstall -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $uninstall -Name NoRepair -Value 1 -Type DWord
Write-Host 'SlothCAD is installed. Start it from the Start menu or the desktop shortcut.' -ForegroundColor Green
