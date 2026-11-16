# Implementation Plan

Each step is small and has a **validation** check. Do not start the next step until the
current one is validated and `progress.md` is updated.

Working rules:
- **Record before code.** Investigation steps (manuals, probes, captures) only *record* findings in
  `docs/protocols.md` (marked 📖 manual / 🔍 capture / ✅ hardware). Driver code and config are
  written afterwards, in Phase 1, from the recorded findings.
- **No motion without explicit permission.** Any command that moves hardware is sent only after
  the user approves that specific move and can check it physically.

---

## Phase 0 — Setup & protocol capture

**0.1 Repository & environment**
- `git init`, `.gitignore` (logs/, captures, `__pycache__`, `.venv`), `pyproject.toml`,
  `src/h2lasercontrol/__init__.py`, `tests/`.
- In `H2LaserControl` env: `pip install pyserial pytest ruff` and `pip install -e .`.
- ✅ Validation: `python -c "import h2lasercontrol, serial"` works; `pytest` runs (0 tests OK).

**0.2 Hardware inventory**
- `tools/list_ports.py`: list COM ports with VID/PID/FTDI serial number/description.
- Plug devices one at a time to map *device ↔ FTDI serial ↔ COM*. Check whether MFF101
  appears as a COM port (enable "Load VCP" if not).
- Record port settings, controller addresses/axis numbers in `config/devices.toml`.
- ✅ Validation: table in `progress.md` mapping every device to its serial number & port.

**0.3 Collect protocol documents**
- Download: ELLx protocol manual (Issue 10), Thorlabs APT protocol PDF, HIT-MV (or HIT-M)
  command manual → `docs/vendor/` (git-ignored if licensing is a concern).
- ✅ Validation: the command subset we need is written down per device in `docs/protocols.md`.

**0.4 Capture vendor-software traffic (verification)**
- HIT-MV and ELL14: capture with a serial monitor or com0com + `tools/serial_relay.py`
  (relay between virtual port and real port, timestamped hex+ASCII log of both directions).
- Perform exactly the operations we use (feedthrough IN/OUT, rotate, home) and save
  captures under `captures/`.
- MFF101: skip sniffing unless the APT manual turns out insufficient (USBPcap fallback).
- ✅ Validation: each needed operation has a captured command matching (or correcting)
  `docs/protocols.md`.

---

## Phase 1 — Control via scripts

**1.1 Transport layer**
- `SerialTransport`: open/close, `write(bytes)`, `read_until(terminator, timeout)`,
  `read_exact(n)`, debug logging of raw bytes. `FakeTransport` for tests (scripted replies).
- ✅ Validation: unit tests with FakeTransport; loopback/echo test on a real port if available.

**1.2 Operation log**
- `oplog.py`: append JSON Lines `{time, user, device, action, args, raw_tx, raw_rx, result, error}`
  to `logs/oplog-YYYY-MM-DD.jsonl`.
- ✅ Validation: unit test writes and re-reads entries; file survives a crash mid-run.

**1.3 Driver base + config**
- `drivers/base.py`: common interface (`connect`, `disconnect`, `identify`, `status`,
  `execute(action, **args)`), every call logged through oplog.
- `config.py`: load `config/devices.toml` (port by serial number, named positions).
- ✅ Validation: config with all three devices loads; port resolution by serial number works.

**1.4 ELL14 driver**
- Operations: `identify` (`in`), `status` (`gs`), `home`, `move_abs(deg)` (`ma`),
  `position()` (`gp`), named angles from config. Degrees↔pulses from the `in` reply.
- ✅ Validation: unit tests (encoding/decoding); on hardware: home, move to 3 angles, read back
  within tolerance; oplog shows all commands.

**1.5 MFF101 driver**
- APT framing (header encode/decode). Operations: `identify` (HW_REQ_INFO),
  `position()` (status bits), `flip(1|2)` (MOT_MOVE_JOG direction) → named `DUMP`/`PASS`.
- ✅ Validation: unit tests on byte frames vs. manual examples; on hardware: flip both ways,
  position read back correctly both ways (known issue: verify *both* directions work).

**1.6 HIT-MV driver**
- Operations (exact syntax from 0.3/0.4): `identify`, `position(axis)`, `is_busy()`,
  `move_abs(axis, pulses)`, `home(axis)`, `stop(axis)`; named `IN`/`OUT` per feedthrough.
- Wait-until-done with timeout; stop on timeout.
- **INSERT = `H:` (origin return); RETRACT = `D:` + `M:` +30000000** (as captured from SGSample,
  see `docs/protocols.md`). Per-operation timeouts (insert/retract ≈ 30–62 s).
- **User requirement: homing max speed F = 1000000 units/s** (same as retract) via
  `B:axis,s,f,r,m` sent before each `H:`, keeping S/R/M unchanged. First read current `?:B0/?:B1`.
  Validate on hardware with permission: insert ≈ 30 s, ends exactly at 0, overshoot acceptable.
- ✅ Validation: on hardware, each feedthrough IN→OUT→IN, positions confirmed; stop works mid-move.

**1.7 Phase 1 demo script**
- `scripts/demo_phase1.py`: connect all, report status, perform the real-world sequence
  (flip DUMP → insert PD → retract PD → flip PASS, rotate ELL14), disconnect.
- ✅ Validation: runs end-to-end on hardware; oplog shows the full history. **Phase 1 done.**

---

## Phase 2 — GUI

**2.1 Device services**: one `QThread` worker per device; command queue; state signals;
periodic status polling; connection-loss detection.
**2.2 Main window**: one panel per device (connect indicator, current named position,
big buttons for named positions, busy indicator); errors shown plainly.
**2.3 Operation log view**: live table of today's oplog; filter by device.
**2.4 Startup/shutdown**: auto-connect from config; safe shutdown; single-instance guard.
**2.5 Launcher**: desktop shortcut / `.bat` activating the conda env.
- ✅ Validation per step on hardware; a non-developer user operates all devices without help.

---

## Phase 3 — Interlock / ordering rules

**3.1 Rule model** (in config): preconditions per action, e.g.
`hitmv.pd_axis -> IN requires mff101.flip == DUMP`; mode per rule: *block with message* or
*auto-perform prerequisite*.
**3.2 Rule engine** in the sequencer; every action checked before execution; unknown
state (device disconnected / position unknown) ⇒ blocked.
**3.3 GUI integration**: disabled buttons with tooltip explaining why; rule violations logged.
- ✅ Validation: unit tests for every rule; on hardware, the unsafe order is impossible from GUI.
- (Detailed rule list to be designed with the user at the start of Phase 3.)

---

## Phase 4 — Programmable operations (macros)

**4.1 Macro model**: named list of actions (+ optional waits) stored in `config/macros.toml`.
**4.2 Runner**: executes through the same sequencer (rules still apply); abort button; progress.
**4.3 GUI**: macro buttons; simple macro editor (or edit TOML at first).
- ✅ Validation: a user creates a macro and runs it; aborting mid-macro leaves devices in a known state.

---

## Later (optional)
Add more devices through the same driver interface; SQLite log with search; packaging as a
standalone exe.
