@echo off
rem Start H2 Laser Control in SIMULATION mode (no hardware is touched; logs go to logs\sim\).
call "%USERPROFILE%\miniconda3\Scripts\activate.bat" H2LaserControl
cd /d "%~dp0"
start "" pythonw -m h2lasercontrol.gui --sim %*
