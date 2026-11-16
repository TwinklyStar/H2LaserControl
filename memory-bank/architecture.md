# Architecture

Status: **planned** (no code yet). Update this file whenever a structural decision is made.

## Layers

```
 GUI (PySide6)            Phase 2   — widgets only; never touches serial ports
   │  actions / state signals
 Sequencer + Rules        Phase 3/4 — ordering rules, user macros
   │  Action("hitmv.axis1", "IN")
 Device services          Phase 1/2 — one worker per device: owns the driver, runs commands
   │                                  off the UI thread, publishes state, writes op-log
 Drivers                  Phase 1   — protocol logic per device (ELL14, MFF101, HIT-MV)
   │  bytes
 Transport                Phase 1   — SerialTransport (pyserial / ftd2xx), raw-byte logging
```

Rules:
1. Each layer only talks to the one below it.
2. **Every** device action goes through the same entry point (`execute(action)`), so
   logging, rules and macros all see the same stream of actions.
3. Drivers expose **named, high-level operations** (`move_to("IN")`, `flip("DUMP")`), with
   raw numbers kept in config.
4. Device identification by USB serial number → COM port resolved at startup.

## Planned source layout

```
src/h2lasercontrol/
  transport/      serial_transport.py, fake_transport.py (for tests)
  drivers/        base.py, ell14.py, mff101.py, hitmv.py
  oplog.py        operation history (JSON Lines)
  config.py       load config/devices.toml
  services/       (Phase 2) device workers
  rules/          (Phase 3)
  macros/         (Phase 4)
  gui/            (Phase 2)
config/devices.toml
tools/            port listing, serial relay/sniffer, captures
tests/
logs/             operation logs (git-ignored)
```

## Insights / decisions log
- Thorlabs MFF101 normally uses the FTDI D2XX driver (Kinesis), not a COM port → its traffic
  is invisible to COM sniffers; we rely on the documented APT protocol for it.
- COM numbers are not stable; identify devices by FTDI serial number.
- Our program and vendor software cannot share a port; vendor software must be closed.
