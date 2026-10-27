Option Explicit
' Ask the background service to stop.
Dim sh, fso, here, py
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
py = "pythonw.exe"
If fso.FileExists(here & "\.venv\Scripts\pythonw.exe") Then py = here & "\.venv\Scripts\pythonw.exe"
sh.CurrentDirectory = here
sh.Run """" & py & """ """ & here & "\tools\start.py"" --stop", 0, False
