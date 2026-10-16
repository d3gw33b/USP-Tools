@echo off
rem Stops the USP bot and stops it starting by itself.
cd /d "%~dp0"
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\USP bot.bat" 2>nul
where py >nul 2>nul
if %errorlevel%==0 (py -3 usp_live.py --stop) else (python usp_live.py --stop)
echo The bot won't start by itself any more.
pause
