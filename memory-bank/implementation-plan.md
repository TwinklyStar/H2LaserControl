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

**0.5 Revisit Phase 0 for devices installed later** (memo, user 2026-11-16)
- **MFF101/M ×2** and **SRS DG645** are not installed yet. Phase 1 proceeds with HIT-MV + ELL14;
  when each device is installed, come back and do 0.2 (port/serial), 0.3 (protocol subset in
  `docs/protocols.md`), 0.4 (capture/verify) for it, then its Phase 1 driver step.
- DG645: RS-232 now, possibly LAN later. Manual `ref/DG645m.pdf`, remote programming from
  **printed page 41**. Which functions we need: ask the user at that time.
- ✅ Validation: same as 0.2–0.4 for each new device.

---

## Phase 1 — Control via scripts

**1.1 Transport layer**
- `SerialTransport`: open/close, `write(bytes)`, `read_until(terminator, timeout)`,
  `read_exact(n)`, debug logging of raw bytes. `FakeTransport` for tests (scripted replies).
- ✅ Validation: unit tests with FakeTransport; loopback/echo test on a real port if available.

**1.2 Operation log**
- `oplog.py`: append JSON Lines `{time, user, device, action, event, args, result, error,
  exchanges: [[tx, rx], ...], duration_s}` to `logs/oplog-YYYY-MM-DD.jsonl`
  (`event` = start | done | failed; raw TX/RX pairs collected per action).
- ✅ Validation: unit test writes and re-reads entries; file survives a crash mid-run.

**1.3 Driver base + config**
- `drivers/base.py`: common interface (`connect`, `disconnect`, `identify`, `status`,
  `execute(action, **args)`), every call logged through oplog.
- `config.py`: load `config/devices.toml` (port by serial number, named positions).
- ✅ Validation: config with all three devices loads; port resolution by serial number works.

**1.4 ELL14 driver**
- Operations: all ELLO panel functions (design F4): `identify` (`in`), `status` (`gs`),
  `get_position` (`gp`), `home(direction)` (`ho0/ho1`), `move_abs/move_rel(deg)` (`ma/mr`),
  `jog_forward/backward` (`fw/bw`), `get/set_home_offset` (`go/so`), `get/set_jog_step`
  (`gj/sj`), `clean` (`cm`), `clean_and_optimize` (`om`), `stop` (`st`), `get_velocity` (`gv`),
  named angles from config. Degrees↔pulses from the `in` reply.
- ✅ Validation: unit tests (encoding/decoding, exact captured bytes); on hardware: home, move to
  3 angles, read back within tolerance; jog, move_rel; `st` reply observed; oplog shows all commands.

**1.5 MFF101 driver** (protocol recorded 2026-11-17, `docs/protocols.md` § MFF101; one unit,
serial 37011815, connected; D2XX, no COM port)
- `transport/d2xx_transport.py`: `D2xxTransport(serial)` via ctypes `ftd2xx.dll`, set-up as
  manual p. 33 (115200 8N1, purge, reset, RTS/CTS, RTS). Config: `usb_serial`, `transport = "d2xx"`.
- APT framing (header encode/decode, read 6 bytes then `len` data bytes). Operations:
  `identify` (HW_REQ_INFO, refuse if model is not MFF*), `status`/`snapshot` (STATUSBITS →
  position 1/2/moving/unknown), `flip_to(1|2)` / named `move_to("DUMP"|"PASS")` (MOT_MOVE_JOG,
  poll status until at position, timeout ≈ transit time + margin), `identify_led`
  (MOD_IDENTIFY), `get_transit_time` (REQ_MFF_OPERPARAMS, read-only). Never EEPROM / SET params.
- Two units, **one tab "Flip mounts" with one card per unit** (user, like the HIT-MV tab): so
  one config entry `type = "mff"` listing `units` (key, label, usb_serial, position names e.g.
  `{1 = "retract", 2 = "insert"}`); the service owns one D2XX transport per unit. A unit that is
  not connected shows as offline on its card without blocking the other.
- At position = limit bit set **and** moving bit 0x10 clear; poll every 50 ms, timeout 3 s
  (transit 500 ms).
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

**1.6b DG645 driver** (manual read 2026-11-17, `docs/protocols.md` § DG645; unit not installed)
Scope (user): **adjust the delay of one channel only.** No trigger/burst/level/output changes;
never `*RST`, `*RCL`, `REMT`, `IFCF`.
- Config `[devices.dg645]`: `type = "dg645"`, port by USB-serial adapter serial, 9600 baud,
  `rtscts = true`; `channel = "A"` (the one channel we adjust), `reference = "T0"` (kept as is
  unless the user says otherwise), `min_s` / `max_s` (allowed range, refused outside),
  `steps_s` (step sizes for ± buttons), `unit = "ns"|"us"` for display. Later LAN:
  `host`, `tcp_port = 5025` → `TcpTransport` (only `_open/_close/_write/_read_some/
  _discard_input`; driver unchanged).
- `drivers/dg645.py` (`Driver` subclass; command = text + `\n`, reply = `read_until(b"\r\n")`):
  - `identify` → `*IDN?`, refuse if it is not a DG645.
  - `get_delay()` → `DLAY?c` → `{channel, reference, delay_s}`.
  - `set_delay(delay_s)` (`moves=False`, logged): check range → `*CLS` → `DLAY c,d,t`
    (t formatted with 12 decimals = 1 ps) → `LERR?` until `0` (any error → `DeviceError` with
    the code's text) → read back `DLAY?c` and require |read − requested| ≤ 5 ps and the same
    reference. Old → new value in the oplog result.
  - `step_delay(delta_s)` = `set_delay(current + delta)` (one oplog entry).
  - `snapshot()` for polling: `DLAY?c` (+ `INSR?` bit 6/7 PLL/Rb unlock as a warning — optional).
- `sim.py`: `Dg645Sim` (parses `*IDN?`, `*CLS`, `DLAY`, `DLAY?`, `LERR?`, `*ESR?`; error queue;
  range/link errors) for tests and `--sim`.
- GUI tab "Delay generator": big display "A = T0 + 12.345 678 µs", entry box (with unit) + **Set**,
  step buttons (−/+ with step-size choice), last change (who/when). No other controls.
- Power-off note: remote changes are not saved by the DG645 (p. 17). Either do nothing (the
  front-panel value returns after power cycle) or save with `*SAV n` — ⏳ user decision.
- ✅ Validation: unit tests vs. simulator and the manual's example strings; on hardware (no
  laser risk, but ask first): `*IDN?`, read delay, set a new value and read it back, check the
  front-panel display shows it, restore the original value; error path (out-of-range value
  → refused by our range check; a raw out-of-range `DLAY` → error 12 seen via `LERR?`).

**1.7 Phase 1 demo script**
- `scripts/demo_phase1.py`: connect all, report status, perform the real-world sequence
  (flip DUMP → insert PD → retract PD → flip PASS, rotate ELL14), disconnect.
- Until MFF101/DG645 are installed: `scripts/status.py` (read-only) + `scripts/ctl.py` (one action
  per call, motion only with `--allow-motion`) cover HIT-MV and ELL14.
- ✅ Validation: runs end-to-end on hardware; oplog shows the full history. **Phase 1 done.**

---

## Phase 2 — GUI

**2.1 Device services**: one `QThread` worker per device; command queue; state signals;
periodic status polling; connection-loss detection.
**2.2 Main window**: **browser-style tabs, one tab per device** (user, 2026-11-17); tab shows a
status dot. Each device panel: connect indicator, current named position, big buttons for named
positions, busy indicator, Stop; errors shown plainly. Panel class chosen by device type, so a new
device = a new tab. Simulation mode (`--sim`) for work without hardware, clearly marked.
**2.3 Operation log view**: live table of today's oplog; filter by device.
**2.4 Startup/shutdown**: auto-connect from config; safe shutdown; single-instance guard.
**2.5 Launcher**: desktop shortcut / `.bat` activating the conda env.
- ✅ Validation per step on hardware; a non-developer user operates all devices without help.

---

## Phase 3 — Interlock / ordering rules

**3.1 Rule model** (in config): preconditions per action. First rule already enforced since Phase 2
(user, 2026-11-17): HIT-MV axis 0 and axis 1 never inserted together (driver + GUI, config
`exclusive_axes`) — move it into the rule engine here. Other example:
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
