' ============================================================
' KeyDrive VBS Launcher for Windows
' ============================================================
' This VBScript launches KeyDrive.bat silently (no console window flash).
' Double-click this file or the .lnk shortcut to start KeyDrive.
' ============================================================

Option Explicit

Dim WshShell, fso, scriptDir, batPath

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get the directory where this VBS file is located
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Build path to the batch file
batPath = fso.BuildPath(scriptDir, "KeyDrive.bat")

' Check if KeyDrive.bat exists
If Not fso.FileExists(batPath) Then
    MsgBox "ERROR: KeyDrive.bat not found at:" & vbCrLf & batPath, vbCritical, "KeyDrive Launcher"
    WScript.Quit 1
End If

' Run the batch file (0 = hidden window)
WshShell.Run """" & batPath & """", 0, False

Set fso = Nothing
Set WshShell = Nothing 
