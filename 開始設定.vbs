Option Explicit
' Start the service in the background (no console window) and open the setup wizard.
Dim sh, fso, here, py
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
py = "pythonw.exe"
If fso.FileExists(here & "\.venv\Scripts\pythonw.exe") Then py = here & "\.venv\Scripts\pythonw.exe"
sh.CurrentDirectory = here
sh.Run """" & py & """ """ & here & "\tools\start.py"" --setup", 0, False
