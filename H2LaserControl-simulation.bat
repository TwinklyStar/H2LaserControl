@echo off
rem Start H2 Laser Control in SIMULATION mode (no hardware is touched; logs go to logs\sim\).
rem Conda is looked for in the usual places; add yours to the list if it is elsewhere.
set "ACT="
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\miniconda3" "%ProgramData%\anaconda3") do (
  if not defined ACT if exist "%%~D\Scripts\activate.bat" set "ACT=%%~D\Scripts\activate.bat"
)
if not defined ACT (
  echo Conda not found. Edit the folder list in "%~f0".
  pause
  exit /b 1
)
call "%ACT%" H2LaserControl
cd /d "%~dp0"
start "" pythonw -m h2lasercontrol.gui --sim %*
