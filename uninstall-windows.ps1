# Removes SlothCAD: program files, Python environment, shortcuts, the .fcad file
# association and the Settings > Apps entry. Your projects (.fcad files) are never
# touched. Settings and autosaves are removed only if you say so.

$ErrorActionPreference = 'Continue'
$Target = Join-Path $env:LOCALAPPDATA 'Programs\SlothCAD'

Add-Type -AssemblyName System.Windows.Forms
$answer = [System.Windows.Forms.MessageBox]::Show(
    "Remove SlothCAD from this computer?`n`nYour projects are kept.",
    'Uninstall SlothCAD', 'YesNo', 'Question')
if ($answer -ne 'Yes') { exit 0 }

$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target, [StringComparison]::OrdinalIgnoreCase) }
if ($running) {
    [System.Windows.Forms.MessageBox]::Show('Close SlothCAD first, then uninstall again.', 'Uninstall SlothCAD', 'OK', 'Warning') | Out-Null
    exit 1
}

foreach ($folder in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
    Remove-Item (Join-Path $folder 'SlothCAD.lnk') -ErrorAction SilentlyContinue
}
$classes = 'HKCU:\Software\Classes'
if ((Get-ItemProperty -Path "$classes\.fcad" -ErrorAction SilentlyContinue).'(default)' -eq 'SlothCAD.Project') {
    Remove-Item -Recurse -Force "$classes\.fcad" -ErrorAction SilentlyContinue
}
Remove-Item -Recurse -Force "$classes\SlothCAD.Project" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SlothCAD' -ErrorAction SilentlyContinue

$data = @((Join-Path $env:APPDATA 'SlothCAD'), (Join-Path $env:LOCALAPPDATA 'SlothCAD'))
$answer = [System.Windows.Forms.MessageBox]::Show(
    "Also delete SlothCAD's settings and autosaves?`n`n(Theme, language and unsaved-work recovery files. Your projects are kept either way.)",
    'Uninstall SlothCAD', 'YesNo', 'Question')
if ($answer -eq 'Yes') { foreach ($folder in $data) { Remove-Item -Recurse -Force $folder -ErrorAction SilentlyContinue } }

# This script lives inside the folder it deletes; step out of it first.
Set-Location $env:TEMP
Remove-Item -Recurse -Force $Target -ErrorAction SilentlyContinue
if (Test-Path $Target) {
    [System.Windows.Forms.MessageBox]::Show("SlothCAD was removed, but some files could not be deleted:`n$Target`n`nDelete that folder by hand.", 'Uninstall SlothCAD', 'OK', 'Information') | Out-Null
} else {
    [System.Windows.Forms.MessageBox]::Show('SlothCAD was removed.', 'Uninstall SlothCAD', 'OK', 'Information') | Out-Null
}
