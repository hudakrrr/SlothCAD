' Starts SlothCAD without a console window. Everything it needs is in this folder.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
If fso.FileExists(here & "\portable.flag") Then
  ' portable mode: settings and autosaves stay in the data folder next to the program
  shell.Environment("Process")("SLOTHCAD_CONFIG_DIR") = here & "\data\settings"
  shell.Environment("Process")("SLOTHCAD_RECOVERY_DIR") = here & "\data\recovery"
End If
args = ""
For Each a In WScript.Arguments
  args = args & " """ & a & """"
Next
shell.CurrentDirectory = here
shell.Run """" & here & "\python\pythonw.exe"" -X utf8 """ & here & "\slothcad_launcher.pyw""" & args, 0, False
