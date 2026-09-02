' Zero-flash wrapper for bot_watchdog.ps1, 2026-08-31 - same reason as
' run_wsl_nginx_startup_hidden.vbs (see that file's own comment): a
' recurring "powershell.exe -WindowStyle Hidden" task action still
' briefly flashes a console window every time it fires, since -WindowStyle
' Hidden hides the window only AFTER conhost.exe has already spun up.
' WScript.Shell.Run's window-style argument (0 = hidden) suppresses this
' at process-creation time instead - genuinely zero visible window, every
' 5 minutes, indefinitely.
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""c:\bot\tools\bot_watchdog.ps1""", 0, False
