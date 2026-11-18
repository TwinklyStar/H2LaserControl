# H2 Laser Control

One Windows program that replaces the vendor programs (Sigma Koki **SGSample**, Thorlabs **ELLO**,
Thorlabs **Kinesis**) for the H2 laser room devices. The GUI has one tab per device and is
meant for lab members who are not experts. Every action is written to an operation log.

| Device | What it does here | Connection | Tab | Status |
|---|---|---|---|---|
| Sigma Koki HIT-MV, 2 linear feedthroughs | VUV photodiode (axis 0) and 45° VUV mirror to the profiler (axis 1), both in the VUV diagnostic chamber | RS-232→USB adapter (FTDI, serial `DU0DFFMCA`), 38400 8N1 RTS/CTS | VUV feedthroughs | ✅ in use |
| Thorlabs ELL14 rotation mount | Half-wave plate before a PBS → 355 nm energy | USB (FTDI COM port, serial `DP06TVEFA`), 9600 8N1 | Rotation mount | ✅ in use |
| Thorlabs MFF101/M flip mounts (2) | Flip a mirror/optic in or out | USB, FTDI **D2XX** (no COM port), APT protocol | Flip mounts | ✅ unit `37011815`; 2nd unit not added yet |
| SRS DG645 delay generator | Adjust the delay of one channel | RS-232 (or LAN) | — | ⏳ planned, no code yet |

Devices are found by their **USB serial number**, so it does not matter which COM number Windows
gives them on a new PC.

---

## 1. Moving to another PC

1. **Copy the whole folder** (e.g. as a zip), including the hidden `.git` folder. The git-ignored
   folders `logs/` (operation history) and `captures/` (raw serial captures) are only in the
   folder copy, not in git. Keep them if you want the history.
2. On the new PC, follow **§2 Setup**. Even if you copied a conda env, run
   `pip install -e ".[dev]"` again: the install points to the folder's old path.
3. Plug in the devices and close SGSample, ELLO and Kinesis (also from the system tray).
4. Run the checks in **§4 Check that it works**.
5. If a device has been replaced, put its new USB serial into `config/devices.toml` (see §6).

## 2. Setup (new PC)

Needed: Windows 10/11, internet access for the installers.

1. **Miniconda** (or Anaconda): https://docs.conda.io/en/latest/miniconda.html.
   The launchers look for it in `%USERPROFILE%\miniconda3`, `%USERPROFILE%\anaconda3`,
   `%LOCALAPPDATA%\miniconda3`, `%ProgramData%\miniconda3` and `%ProgramData%\anaconda3`.
2. **Git for Windows** (for development only): https://git-scm.com/download/win.
3. **FTDI drivers.** All devices use FTDI USB chips.
   - COM-port devices (ELL14, HIT-MV adapter): Windows normally installs the driver by itself.
   - Flip mounts need `ftd2xx.dll` (FTDI D2XX). It comes with the FTDI "CDM" driver
     (https://ftdichip.com/drivers/d2xx-drivers/) and with Thorlabs Kinesis. Check that
     `C:\Windows\System32\ftd2xx.dll` exists. This PC has version 3.2.21.1.
   - Vendor software (Kinesis, ELLO, SGSample) is **not** needed to run this program. It is
     useful for comparison and as a fallback.
4. **Python environment.** In an *Anaconda Prompt*, from the project folder:
   ```bat
   conda create -n H2LaserControl python=3.12 pip -y
   conda activate H2LaserControl
   pip install -e ".[dev]"
   ```
   This installs pyserial, PySide6, pytest, pytest-qt and ruff. Versions tested on 2026-11-17:
   Python 3.12.16, pyserial 3.5, PySide6 6.12.0, pytest 9.2.0, pytest-qt 4.5.0, ruff 0.17.5.
   For reading the PDF manuals in `ref/` an agent may also want `pip install pypdf`.
5. Optional: put a desktop shortcut to `H2LaserControl.bat`.

## 3. Running

| What | How |
|---|---|
| GUI, real devices | double-click **`H2LaserControl.bat`** |
| GUI, simulated devices (safe; nothing moves) | double-click **`H2LaserControl-simulation.bat`** (yellow banner; logs go to `logs/sim/`) |
| GUI from a prompt | `python -m h2lasercontrol.gui [--sim] [--no-connect] [--config path]` |
| Read-only status of all devices | `python scripts/status.py [--debug]` |
| One action from the command line | `python scripts/ctl.py list` · `python scripts/ctl.py <device> <action> key=value …` (actions that move need `--allow-motion`) |
| List COM ports with USB serials | `python tools/list_ports.py` |

Only one program can use a device at a time: **close SGSample / ELLO / Kinesis first.** Only one
copy of this program can run at a time (lock file).

**Operation log:** `logs/oplog-YYYY-MM-DD.jsonl`, one JSON line per action. A line holds the time,
the operator, the device, the action, start/done/failed, the arguments and result, and the exact
bytes sent and received. The GUI shows today's history under the tabs. Set the operator name at
the top right.

## 4. Check that it works (after setup)

Run these in order, with the env active (`conda activate H2LaserControl`), from the project folder:

1. **Tests** (no hardware needed). Expected: all pass (86 on 2026-11-17).
   ```powershell
   $env:QT_QPA_PLATFORM = "offscreen"; python -m pytest -q
   ```
2. **Simulation GUI:** `H2LaserControl-simulation.bat`. Three tabs appear and all of them connect.
3. **Read-only hardware check** (nothing moves): `python scripts/status.py`. Each device should
   report its identity and position. If a device is "not found", see §7.
4. **Real GUI:** `H2LaserControl.bat`. Check that the states match reality (normally both
   feedthroughs RETRACTED). Do not move anything unless the beamline situation allows it.

## 5. Safety rules built into the program

- **HIT-MV:** the two feedthroughs are never inserted at the same time (driver interlock and GUI
  lock). Retract is always allowed. "Insert" = origin return (`H:`) to 0. Retracted = 30000000
  units (60 mm real; 1 unit = 2 nm). Insert starts at once (no confirmation dialog, user's choice). STOP stops a move.
- **ELL14:** home offset ≥ 0.7°; continuous jog is not offered. "Go to min energy" =
  max-energy angle + 45°. The max-energy angle is saved in `config/saved_angles.json`
  (30.9877° on 2026-11-17).
- **Flip mounts:** the position is read from the hardware limit bits on every poll, never from
  memory. A flip takes ~0.4 s and has no STOP. A unplugged unit is shown offline and retried
  every 5 s.
- **Position after a power cycle:** HIT-MV and ELL14 positions are counters inside the
  controller. They survive a program reconnect, but they may be wrong after the *controller* is
  switched off and on. Homing (HIT-MV Insert; ELL14 Home) makes them correct again. Whether the
  HIT-MV counter survives a power cycle has not been checked yet.

## 6. Configuration: `config/devices.toml`

- Each device has a `type` (`hitmv`, `ell14`, `mff`), a tab `label` and its USB serial.
- If the serial is not found, connecting **fails**. It never falls back to a COM number, which
  could belong to another device.
- To find serials: COM-port devices with `python tools/list_ports.py`. Flip mounts: the serial
  is printed on the unit, or see Kinesis or Device Manager → "APT USB Device" → Details →
  Device instance path.
- **Second flip mount:** add a block like this:
  ```toml
  [devices.flipmounts.units.flip2]
  label = "Flip mount 2"
  usb_serial = "<serial>"
  insert_position = 2   # which of the two positions (1 or 2) is "insert"
  ```
- Another device of a known type = a new config entry only. A new device type = a driver, a
  simulator and a GUI panel (see `memory-bank/architecture.md`).

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| "not found" for a COM device | Check the cable; run `tools/list_ports.py` and compare the serial with `devices.toml`. |
| Port busy / access denied | Close SGSample / ELLO, or another copy of this program. |
| Flip mount "in use by another program" (FT_STATUS 3) | Close Kinesis, also from the system tray. If that does not help, unplug and re-plug its USB cable. |
| Flip mount: `ftd2xx.dll` not found | Install the FTDI CDM driver or Kinesis (§2.3). |
| Launcher closes at once / "Conda not found" | Conda is installed somewhere else: edit the folder list at the top of the `.bat` file. |
| HIT-MV position looks wrong after a power cut | Retract/insert once with the user watching (homing resets the counter). |

---

## 8. For developers and AI agents: catching up

Read in this order (≈15 min):

1. **`CLAUDE.md`**: working rules for agents (motion permission, record before code, git).
2. **`memory-bank/progress.md`**: current status, the dated log of everything done and
   verified on hardware, **open questions** and **next steps**. Start here for "what next".
3. `memory-bank/design-document.md`: requirements (F-numbers) from the user.
4. `memory-bank/architecture.md`: layers, source layout, key mechanisms, pitfalls found.
5. `memory-bank/implementation-plan.md`: phases 0–4 and the steps in each.
6. `memory-bank/tech-stack.md`: libraries and why.
7. `docs/protocols.md`: every device's command set, byte by byte. Each fact is marked as from
   the manual, a capture, or a hardware test. `docs/captures/` holds compact capture logs.
8. `ref/`: vendor manuals (HIT-MV in Japanese, ELLx, APT protocol, DG645) and the system paper.

Architecture in one picture:

```
GUI (PySide6, one tab per device: gui/panels/*)        never touches ports
  │ submit(action)            ▲ state/progress signals
DeviceService (one QThread per device)                 services/device_service.py
  │ driver.execute(action)    → op-log entry (oplog.py)
Driver (protocol logic, safety checks)                 drivers/hitmv.py, ell14.py, mff.py
  │ bytes
Transport (Serial / FTDI D2XX / Fake for tests)        transport/
```

Phases: 0 capture vendor traffic ✅ · 1 drivers + scripts ✅ (DG645 pending) · 2 GUI ✅ (in use;
finishing touches) · 3 interlock/ordering rules across devices · 4 user macros.

Tests run against simulators (`sim.py`) that reproduce the real devices' replies. Lint:
`ruff check .`
