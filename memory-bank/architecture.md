# Architecture

Status: **Phase 1 code in place** (transport, oplog, config, ELL14 + HIT-MV drivers, simulators).
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
                  serial_transport.py, fake.py (FakeTransport + ScriptedResponder)
  drivers/        base.py (Driver, @action(moves=...), DeviceError/DeviceTimeout/Aborted),
                  ell14.py, hitmv.py, __init__.py (create_driver(cfg) factory)
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

## Insights / decisions log
- Thorlabs MFF101 normally uses the FTDI D2XX driver (Kinesis), not a COM port → its traffic
  is invisible to COM sniffers; we rely on the documented APT protocol for it.
- COM numbers are not stable; identify devices by FTDI serial number. If the serial number is
  not found, **fail** — never fall back to the configured COM number (could be another device).
- Our program and vendor software cannot share a port; vendor software must be closed.
- ELL14 terminator: default `0x07` like ELLO (proven by capture); configurable (`terminator = ""`).
