# H2 Laser Control

A Windows desktop program for controlling and monitoring the devices in the H2 laser room from
one window.

- **Control** tab: VUV feedthroughs (Sigma Koki HIT-MV), rotation mount (Thorlabs ELL14),
  flip mounts (Thorlabs MFF101), laser trigger delay (SRS DG645: only our channel is changed,
  within fixed limits; the other channels are shown read-only).
- **DAQ** tab: PicoScope photodiode monitor, VUV photodiode snapshot, IDS beam camera.
- Every action is recorded in an operation log, with the operator's name.
- A simulation mode lets you try everything without hardware.
- Light and dark theme, following the Windows setting.

## Requirements

- Windows 10 or 11
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) (or Anaconda)
- Device drivers, depending on what you use:
  - Flip mounts: FTDI D2XX driver ([FTDI](https://ftdichip.com/drivers/d2xx-drivers/), also
    installed with Thorlabs Kinesis)
  - Delay generator: the driver of its RS-232–USB adapter (Prolific PL2303)
  - PicoScopes: [PicoSDK, 64-bit](https://www.picotech.com/downloads)
  - Camera: [IDS peak](https://ids-imaging.com/ids-peak)

## Installation

Open an **Anaconda Prompt** in the project folder and run:

```bat
conda create -n H2LaserControl python=3.12 pip -y
conda activate H2LaserControl
pip install -e ".[dev]"
```

Optionally, put a desktop shortcut to `H2LaserControl.bat`.

## Usage

| To start | Do this |
|---|---|
| The program with real devices | Double-click `H2LaserControl.bat` |
| A safe simulation (nothing moves) | Double-click `H2LaserControl-simulation.bat` |

Before starting, close other programs that use the same devices (SGSample, ELLO, Kinesis,
PicoScope 7, IDS peak Cockpit).

- Enter your name at the top right; it is written to the operation log.
- **Control devices** connect by themselves. Their current state is shown on each sub-tab.
- **DAQ devices** start only when you press **Start**. Choose the setup in the **Config** list
  first. A running acquisition continues while you look at other tabs.
- The history of today's actions is shown under the tabs.

> The feedthroughs sit on a live beamline. **Insert** puts them into the beam. Only insert when
> the beamline situation allows it. The two feedthroughs can never be inserted at the same time.

### Where files are saved

| What | Where |
|---|---|
| PicoScope waveforms (ROOT) and trend data (CSV) | `data/picoscope/` |
| Snapshots | `data/picoscope/snapshots/` |
| Camera images | `data/camera/<date>/` |
| Operation log | `logs/oplog-<date>.jsonl` |
| Simulation output | `logs/sim/` (never mixed with real data) |

### Command line

With the environment active (`conda activate H2LaserControl`):

```bat
python -m h2lasercontrol.gui [--sim] [--no-connect]   :: start the program
python scripts/status.py                             :: read-only status of all devices
python tools/list_ports.py                           :: list COM ports and USB serials
python tools/bmp_to_root.py <file or folder>         :: convert camera BMPs to ROOT
```

## Configuration

Devices are listed in `config/devices.toml` and are found by their **USB serial number**, so the
COM port number does not matter. If a device is replaced, enter its new serial there.

- PicoScope setups: `config/picoscope/*.toml`
- Camera settings: `config/camera/*.toml`

## Troubleshooting

| Problem | Fix |
|---|---|
| A device shows "not found" | Check the cable. Run `python tools/list_ports.py` and compare the serial with `config/devices.toml`. |
| "Port busy" / "in use by another program" | Close SGSample, ELLO, Kinesis (also from the system tray), or another copy of this program. If that does not help, unplug and re-plug the device. |
| The launcher closes at once / "Conda not found" | Conda is installed in an unusual place. Edit the folder list at the top of the `.bat` file. |
| Feedthroughs show "POSITION UNKNOWN" | The controller was switched off and lost its position. Check both feedthroughs by eye and home them with the vendor software, then reconnect. |
| PicoScope or camera does not open | Close PicoScope 7 / IDS peak Cockpit and the old DAQ programs, then re-plug the USB cable. |
| "No trigger for 10 s" | No trigger signal arrives (laser off, cable, trigger level). The acquisition keeps waiting. |

Debug logs are in `logs/h2lasercontrol.log` and `logs/fault.log`.

## Project layout

```
config/      device list and acquisition settings
src/         the program (package h2lasercontrol)
scripts/     command-line status and control
tools/       helper tools (port list, probes, file conversion)
tests/       automated tests (run without hardware)
docs/        device command reference
ref/         vendor manuals
```

## Running the tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"; python -m pytest -q
ruff check .
```
