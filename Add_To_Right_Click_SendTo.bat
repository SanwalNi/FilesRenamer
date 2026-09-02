@echo off
setlocal
echo Setting up Windows Right-Click "Send To" shortcut...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut(\"$env:APPDATA\Microsoft\Windows\SendTo\Auto-Rename with Gemini.lnk\"); $Shortcut.TargetPath = $env:ComSpec; $Shortcut.Arguments = '/c py \"' + '%~dp0rename.py' + '\"'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.IconLocation = 'imageres.dll,67'; $Shortcut.Save()"

echo.
echo ========================================================
echo  SUCCESS! 
echo  Now you can RIGHT-CLICK ANY FOLDER in Windows Explorer:
echo  -^> "Send to" -^> "Auto-Rename with Gemini"
echo.
echo  The terminal window will open, run smoothly, and stay open!
echo ========================================================
echo.
pause
