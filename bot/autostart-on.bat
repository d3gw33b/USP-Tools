@echo off
rem Starts the USP bot in the background now, and every time you log in to Windows.
cd /d "%~dp0"
if not exist bot.env (
  echo Make bot.env first: copy bot.env.example, rename the copy to bot.env, and fill in the values.
  pause
  exit /b 1
)
set "PYW=pythonw"
where pyw >nul 2>nul && set "PYW=pyw -3"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
> "%STARTUP%\USP bot.bat" echo @start "" /d "%~dp0." %PYW% usp_live.py
start "" /d "%~dp0." %PYW% usp_live.py
echo Done. The bot is running in the background and starts by itself when you log in.
echo Its log is bot.log in this folder. To turn this off, run autostart-off.bat.
pause
