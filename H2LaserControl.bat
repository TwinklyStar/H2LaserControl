@echo off
rem Start H2 Laser Control (real devices). Close SGSample / ELLO first: ports cannot be shared.
call "%USERPROFILE%\miniconda3\Scripts\activate.bat" H2LaserControl
cd /d "%~dp0"
start "" pythonw -m h2lasercontrol.gui %*
