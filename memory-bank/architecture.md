# Architecture

Status: Phases 1-2 in use; DAQ merge (F8) in code, hardware test pending.
Update this file whenever a structural decision is made.

## Layers

```
 GUI (PySide6)            Phase 2   — widgets only; never touches serial ports
   │  actions / state signals
 Sequencer + Rules        Phase 3/4 — ordering rules, user macros
   │  Action("hitmv", "insert", axis=1)
 Device services          Phase 2   — one worker thread per device: owns the driver, runs
   │                                  actions off the UI thread, publishes state
 Drivers                  Phase 1   — protocol logic per device; execute() writes the op-log
   │  bytes
 Transport                Phase 1   — SerialTransport (pyserial) / FakeTransport; TCP later (DG645)
```

Rules:
1. Each layer only talks to the one below it.
2. **Every** device action goes through `Driver.execute(action, **args)`, so logging, rules and
   macros all see the same stream of actions.
3. Drivers expose **named, high-level operations** (`insert(axis)`, `move_to(name)`), with raw
   numbers kept in config.
4. Device identification by USB serial number → COM port resolved at startup.

## Source layout (actual)

```
src/h2lasercontrol/
  transport/      base.py (Transport ABC: buffering, read_until/read_exact, raw debug log),
                  serial_transport.py, d2xx_transport.py (FTDI D2XX via ctypes ftd2xx.dll, opened
                  by USB serial — Thorlabs APT devices without COM port), fake.py
  drivers/        base.py (Driver, @action(moves=...), DeviceError/DeviceTimeout/Aborted),
                  ell14.py, hitmv.py, mff.py (flip mounts: one driver, several units, one D2XX
                  transport per unit), __init__.py (create_driver(cfg) factory)
  oplog.py        operation history (JSON Lines, fsync per line)
  config.py       load config/devices.toml, resolve_port() by USB serial
  sim.py          HitMvSim, Ell14Sim — simulated devices for tests / GUI work without hardware
  energy.py       HWP+PBS energy math (cos²) + AngleStore (config/saved_angles.json, atomic write)
  services/       device_service.py — DeviceService: one QThread per device, owns the driver
  gui/            app.py (entry, --sim, single-instance lock), main_window.py (tabs + history),
                  log_panel.py, style.py, panels/ (base.py DevicePanel, hitmv_panel.py,
                  ell14_panel.py, PANELS registry by device type)
  rules/ macros/  (Phase 3–4, not yet)
config/devices.toml
scripts/          status.py (read-only status of all devices), ctl.py (one action from CLI;
                  motion only with --allow-motion)
tools/            port listing, read-only probe, capture parser
tests/            pytest; drivers tested against simulators and exact captured bytes
logs/             operation logs (git-ignored)
```

## Key mechanisms
- **Transport** keeps its own receive buffer: `read_until(b"\r\n")` copes with split replies and
  keeps bytes after the terminator. A TCP transport only implements `_open/_close/_write/
  _read_some/_discard_input`. Drivers call `reset_input()` before each command (drop stale replies).
- **Action registry**: methods decorated `@action(moves=True|False)`; `Driver.actions()` lists them
  (used by ctl.py, later by the GUI and the rule engine). `moves=True` ⇒ a `start` entry is logged
  before the action, so a crash during a 60 s move still leaves a record.
- **Op-log entry**: `{time, user, device, action, event: start|done|failed, args, result, error,
  exchanges: [[tx, rx], ...], duration_s}`. Status polling inside waits is not recorded (would
  flood the log); the commands that change something are.
- **Threading**: a driver is used from one thread. `request_stop()` is the only cross-thread call:
  wait loops (`_sleep_or_stop`) see it, stop the device (`L:` / `st`) and raise `Aborted`.
- **HIT-MV interlock (F2a)**: never two feedthroughs inserted. Driver `_check_interlock` before
  `insert` / `move_abs` away from retracted: every other axis must be exactly retracted and not
  busy (unknown ⇒ blocked); retract is never blocked. GUI mirrors it: the other card's Insert is
  disabled with "🔒 Locked: retract the … first". Config `exclusive_axes = true`. Moves into the
  Phase 3 rule engine later.
- **Safety checks in drivers**: HIT-MV checks `!:` before any command (busy → NG), refuses
  unconfigured axes, retract = `M:+(30000000 − current)` (also after a stop halfway), `move_abs`
  only within [0, 30000000],
  stops the axis on timeout; refuses to run if `?:Z` ≠ HIT mode. ELL14 refuses jog step 0
  (continuous jog), home offset ≤ 0.7°, absolute angles outside [0, 360).

- **Multi-unit device (flip mounts)**: config `type = "mff"` with `[devices.X.units.Y]`
  (usb_serial, label, insert_position 1|2). `Mff` overrides connect/disconnect/is_connected:
  connect succeeds if ≥ 1 unit answers; a missing unit is shown offline and retried by
  `snapshot()` every 5 s; a USB error of one unit (`_guard`) takes only that unit offline.
  `Driver.connection_text()` / `drop_connection()` hooks let the service stay device-agnostic.
  No STOP for flips (0.5 s; MFF has no stop message) → the tab hides STOP.

## GUI (Phase 2)
- **Browser-style tabs, one per device** (user requirement). `PANELS[type]` picks the tab class;
  a new device type = one new `DevicePanel` subclass; another device of a known type = config
  entry only. Tab title from config `label`; tab icon = status dot (green ok, blue busy, grey
  off, red error). Operation history (today, live, filter by device) below the tabs.
- `DevicePanel` base: header (connection, busy text, STOP, Connect/Disconnect), plain error line,
  `build_body()` / `update_view()` / `on_progress()` hooks. Buttons are enabled only when the
  action makes sense (e.g. Retract only from INSERTED), with tooltips saying why not.
- `DeviceService` (QObject moved to its own QThread): `submit(action, **kw)` queued to the worker;
  signals connection_changed / busy_changed / state_changed / progress / action_done / failed;
  idle polling via `driver.snapshot()` (not logged), 2 failed polls ⇒ "connection lost".
- ⚠ **STOP must call `service.request_stop()` directly from the GUI thread**, never via a signal
  connection to the service: the service lives in the worker thread, so Qt queues the call behind
  the running action (found in testing: stop arrived only after the move finished).
- ⚠ The stop flag is cleared by the service *before* "busy" is announced and by `execute()` after
  each action — not at the start of `execute()` (a STOP pressed in between would be lost).
- Operator name field (top right) → `oplog.user` (remembered in QSettings). `--sim` mode: yellow
  banner, logs to `logs/sim/`. Single-instance lock (two programs can't share ports).
- Launchers: `H2LaserControl.bat`, `H2LaserControl-simulation.bat`.

## DAQ devices (F8, merged 2026-11-18)
Streaming devices (25 Hz waveforms / frames) do not fit `Driver.execute` (command → reply), so
they have their own path next to DeviceService. Start / pause / stop / errors / saves go to the
op log; the data goes straight to files and plots.

```
src/h2lasercontrol/
  daq/picoscope/  assistant.py  RootManager + ADC helpers (copied, ROOT format unchanged)
                  digitizer.py  Digitizer(threading.Thread) = old H2LaserDigitizer: opens the
                                scope in its own thread, block-capture loop, ROOT/CSV, queue items
                  virtual.py    VirtualDigitizer (simulation; real loop, fake hardware hooks)
                  session.py    PicoSession: the digitizers of one tab; start/pause/resume/stop,
                                poll() -> plot items, op log; plain Python (no Qt)
                  configs.py    config/picoscope/*.toml (one file = title, mode, digitizers with
                                the old keys); load + validate, list by mode
  laserdaq/       old IDS-Camera package, copied unchanged except: configs_dir/base_dir
                  parameters of its MainWindow, output_dir default data/camera, mock without
                  the 12 MB Ref BMP -> synthetic spot. cli/ (TUI) and camera/select.py dropped.
  gui/daq/        scope_views.py  ContinuousView / SnapshotView (ported pyqtgraph windows)
                  scope_tab.py    ScopeTab: start page <-> running page (Pause-Resume / Stop,
                                  per-scope status line, plot view made on each Start)
                  camera_tab.py   CameraTab: start page <-> embedded laserdaq MainWindow
                  DAQ_TABS registry by type ("picoscope", "ids_camera")
config/devices.toml  [devices.scope_monitor|vuv_pd] type "picoscope", mode, config_dir,
                     default_config; [devices.camera] type "ids_camera"
config/picoscope/    scope setups (old H2LaserDAQ config/*.py converted; chosen in the tab's
                     drop-down, which shows only files of the tab's mode)
config/camera/       camera settings TOMLs (old configs/, output_dir = data/camera)
data/picoscope/      root/, csv/, snapshots/ (git-ignored);  data/camera/YYYY-MM-DD/... 
```
- **Threads**: one thread per scope; it opens, uses and closes its own scope (open takes 3-4 s,
  never on the GUI thread). Each digitizer has its own stop flag: a failing scope stops alone
  (red in its tab, `failed` in the op log). The GUI polls the session queue at 10 Hz.
- **Pause** = no trigger armed, nothing written, files and scope stay open; an armed block is
  aborted (`ps*Stop`) and *not* written. Resume continues in the same files.
- ⚠ `threading.Thread` has an internal `_stop()`: never name an attribute `_stop` in a Thread
  subclass (it broke `join()`; flag is `_stop_evt`).
- **SDK locks**: every ps2000 / ps3000a call holds a per-DLL lock (driver thread safety is not
  documented). `ps2000_open_unit` has no serial argument: open all free units, keep ours,
  close the rest, under the lock, so two tabs starting together cannot grab each other's unit.
  Cost: while a 2204A is being opened (~3.7 s per unit) the other 2204A misses triggers.
- **Camera**: the camera window keeps its own threading (acquisition thread owns the SDK). The
  tab creates it on Start and deletes it on Close (each open = a fresh window, like restarting
  the old program). `recording_finished` -> op-log `record` entry.
- **Style**: the app style sheet's general rules are limited to our classes (`style.OWN`:
  DevicePanel, ScopeTab, CameraStartPage, CameraHeader, LogPanel, TopBar) so the embedded
  camera window looks like the old program (its sidebar has a fixed 276 px width).
- **Sim**: `--sim` uses VirtualDigitizer / MockCamera and writes data to `logs/sim/data/...`.
- Diagnostics from the camera program are now app-wide: `logs/h2lasercontrol.log` (+ `.prev`),
  `logs/fault.log` (native crashes, GUI-freeze stack dumps by HangWatchdog after 3 s).

## Insights / decisions log
- Thorlabs MFF101 normally uses the FTDI D2XX driver (Kinesis), not a COM port → its traffic
  is invisible to COM sniffers; we rely on the documented APT protocol for it.
- COM numbers are not stable; identify devices by FTDI serial number. If the serial number is
  not found, **fail** — never fall back to the configured COM number (could be another device).
- Our program and vendor software cannot share a port; vendor software must be closed.
- ELL14 terminator: default `0x07` like ELLO (proven by capture); configurable (`terminator = ""`).
