' Zero-flash wrapper for wsl_nginx_startup.ps1, 2026-08-29.
' REASON: the Scheduled Task's own "powershell.exe -WindowStyle Hidden"
' action still briefly flashed a console window every time it fired
' (every 2 minutes, per the new recurring trigger) - a known Windows
' quirk: -WindowStyle Hidden hides the window AFTER conhost.exe has
' already spun up, so the flash still happens for a console-subsystem
' app like powershell.exe (unlike pythonw.exe, which has no console
' subsystem at all and never flashes). WScript.Shell.Run's window-style
' argument (0 = hidden) suppresses this at process-creation time itself -
' the standard, reliable way to run a console script with truly zero
' visible window.
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""c:\bot\tools\wsl_nginx_startup.ps1""", 0, False
