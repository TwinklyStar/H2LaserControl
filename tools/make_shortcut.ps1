# Create or update the desktop shortcut "H2 Laser Control" with the program icon.
# A .bat file cannot have its own icon; a shortcut to it can.
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1 [-Simulation]
param([switch]$Simulation)

$root = Split-Path -Parent $PSScriptRoot
$bat = if ($Simulation) { 'H2LaserControl-simulation.bat' } else { 'H2LaserControl.bat' }
$name = if ($Simulation) { 'H2 Laser Control (simulation).lnk' } else { 'H2 Laser Control.lnk' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop $name))
$link.TargetPath = Join-Path $root $bat
$link.WorkingDirectory = $root
$link.IconLocation = (Join-Path $root 'src\h2lasercontrol\gui\icon\h2lasercontrol.ico') + ',0'
$link.WindowStyle = 7  # minimized: the short-lived console window of the .bat stays hidden
$link.Description = 'H2 Laser Control'
$link.Save()
Write-Output "Shortcut: $(Join-Path $desktop $name)"
