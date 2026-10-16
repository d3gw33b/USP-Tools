@echo off
rem Runs the USP bot in this window so you can watch it. Close the window to stop it.
cd /d "%~dp0"
if not exist bot.env (
  echo Make bot.env first: copy bot.env.example, rename the copy to bot.env, and fill in the values.
  pause
  exit /b 1
)
where py >nul 2>nul
if %errorlevel%==0 (py -3 usp_live.py) else (python usp_live.py)
pause
