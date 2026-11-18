# Progress

## Current status
- **Phase 0 — done** (MFF101 parts deferred until installed). 0.1 ✅, 0.2 ✅, 0.3 ✅, 0.4 ✅
  (HIT-MV both axes, ELL14 all ELLO functions).
- **Phase 1 — in progress.** 1.1 ✅, 1.2 ✅, 1.3 ✅ (2 devices; MFF101/DG645 not installed).
  **1.4 ELL14 ✅ and 1.6 HIT-MV ✅ validated on hardware** (2026-11-17, incl. post-stop settle fix).
- **Phase 2 — in progress** (started 2026-11-17). 2.1 services ✅, 2.2 tabbed main window ✅,
  2.3 history panel ✅, 2.4 startup/shutdown ✅, 2.5 launchers ✅ — tested in simulation and
  **on the real devices by the user ✅** (2026-11-17). ⏳ Left: retract-from-partial on hardware,
  usability check by a non-developer lab member. 1.5 MFF101 / 1.6b DG645 wait for 0.5 (not installed). 1.7 demo needs MFF101.

## Device inventory
| Device | Qty | Port | FTDI serial | Status |
|---|---|---|---|---|
| Thorlabs ELL14 | 1 | COM3 | DP06TVEF | connected |
| Sigma Koki HIT-MV (2 linear feedthroughs) | 1 | COM4 (RS-232→USB adapter) | DU0DFFMC | connected |
| Thorlabs MFF101/M | 2 | — | — | **not installed yet** (future) |
| SRS DG645 delay generator | 1 | RS-232 (LAN later?) | — | **not installed yet** (future); manual `ref/DG645m.pdf`, programming from printed p. 41 |

## Log
### 2026-11-16
- Created memory-bank docs: design-document, tech-stack, implementation-plan, architecture.
- Agreed phases: 1 script control → 2 GUI → 3 interlock/ordering → 4 user macros.
  Target positions will be discussed when we reach that step.
- Conda env `H2LaserControl` was empty (no Python); installed **Python 3.12.16** + pip,
  pyserial 3.5, pytest, ruff, pypdf.
- Installed Git for Windows 2.56; `git init -b main` done, `.gitignore` written.
- HIT-MV manual (`ref/HIT-MV_jp.pdf`, Japanese) read: port settings (38400 default, 8N1,
  RTS/CTS, CR+LF) and HIT-mode command set summarized in `docs/protocols.md`.

- Git identity set (repo-local, author "Meng"). Package skeleton (`pyproject.toml`,
  `src/h2lasercontrol`, `tests/`), `tools/list_ports.py`, `tools/probe_readonly.py` added;
  editable install OK, pytest OK, ruff OK. First commit `cc9b7a5`. **Step 0.1 done.**
- pyserial reports FTDI serials with suffix `A`: COM3 = `DP06TVEFA`, COM4 = `DU0DFFMCA`.

- **Read-only probe succeeded** (vendor software closed), details in `docs/protocols.md`:
  - HIT-MV: 38400 8N1 RTS/CTS, firmware V1.20-001, **HIT mode**, axes **0 and 1** connected,
    both at 30000000 (= 60 mm real; see scale note below), ready, no alarms.
  - ELL14: serial 11401124, OK status, position 0x3040 ≈ 31.02°, 143360 pulses/360°.
  - Created `config/devices.toml` (ports by USB serial). **Step 0.2 done.**

- System paper added (`ref/NIMA_vuv_light_source.pdf`). Axis mapping confirmed by user:
  axis 0 = VUV photodiode, axis 1 = 45° VUV mirror (to profiler), both in VUV diagnostic chamber.
  Retracted = 30000000 units (normal), inserted = 0. Recorded in config, design doc, protocols.
- Decision: **do step 0.4** (capture vendor-software traffic) to make sure we reproduce the
  existing operation exactly. Capture method to be chosen.
- Vendor software: Sigma Koki **SGSample** (HITSample.exe), Thorlabs **ELLO**.
- **Insert = ORG (H:) in SGSample**; mechanical origin = 0 = inserted. Retract = move to 30000000.
- HITSample.exe strings confirm it uses HIT-mode commands from the manual.
- Rule from user: **only the mirror (axis 1) may be moved during capture, and only after asking
  the user for explicit permission each time** (user checks the motion physically).

- Step 0.4 started: Eltima monitor Table view redirected to `captures/hitmv_table.txt`;
  `tools/parse_spm_table.py` summarizes it (handles stray line breaks in the redirect file).
  Captured SGSample **connect + idle** (no motion): settings 38400 8N1 RTS/CTS confirmed; connect
  sequence `?:N, ?:Z, per-axis ?:Dn/?:S/Q:/!:/Q:S, F:MU`; idle polling `Q:` ~2 Hz.
  Axes 0/1 speed: S=100000, F=1000000 units/s (real 0.2 / 2 mm/s), R=200 ms. Details in `docs/protocols.md`.
- **Mirror insert/retract captured** (user-approved, checked physically), 18:51–18:53:
  INSERT = `H:,1,,,,,,` (~62 s, homing overshoots ≈0.1 mm real then settles at 0);
  RETRACT = `D:1,100000,1000000,200` + `M:,+30000000,,,,,,` (relative +60 mm real, ~30 s).
- **Scale correction (user):** 30000000 units = **60 mm real** → 1 unit = 2 nm; the manual's
  0.01 µm/unit (and `?:P` 0.10 µm/pulse) don't match the fitted stages. Real = nominal ÷ 5.
  Docs corrected; always command in raw units, convert only for display.
  SGSample "timeout" popup = its own fixed ~30 s timeout during the 62 s homing; controller OK.
  Compact log committed in `docs/captures/`. Lesson: SPM redirect file caps at 512 MB — always
  apply the filter / untick Device Control.
- **Photodiode (axis 0) insert/retract captured** by user (19:03–19:04): `H:1,,,,,,,` (62 s),
  `D:0,100000,1000000,200` + `M:+30000000,,,,,,,` (30 s). Identical to axis 1 with slot p0.
  Homing turn-around differs per axis (axis 0 +83920, axis 1 −49800) → counter drifts ~0.1–0.2 mm
  real from the physical origin between homings; homing removes it. Recorded in protocols.md.
- **HIT-MV part of step 0.4 done** (both axes).

- Capture tool: Eltima / Electronic Team **Serial Port Monitor 9.5.602** (user-installed,
  signatures valid, sniffer driver `SPSniff`). HHD installer discarded (unverified signer).

- **User requirement recorded:** homing F = 1000000 units/s (via `B:` before `H:`, S/R/M kept).
  In implementation-plan 1.6, design-document F2, protocols.md. Read `?:B0/?:B1` first.

- **ELL14 scope (user):** all ELLO panel functions are needed (home + direction, home offset
  get/set, jog step get/set, jog fw/bw, move abs/rel, update, clean, clean & optimize, stop).
  Current ELLO values: offset 3.214°, home anticlockwise, jog 5.0°. Expected commands listed in
  protocols.md (📖, to confirm by capture). Design doc F4 updated.

- **ELL14 ELLO capture done** (20:18–20:20, user-operated; Clean & Optimize skipped by choice).
  All expected commands confirmed; ELLO appends `0x07` to every command; replies may arrive split;
  home = `ho1` (anticlockwise); Home Direction is ELLO-local; motion reply `PO` comes at the end
  of motion; `cm` → `GS09` (busy) then `st`. Details in protocols.md, compact log in docs/captures/.
  (`parse_spm_table.py` pairs by CR LF, so it doesn't split ELL14 TX — fix in Phase 1 tooling.)
- **Cross-check vs. manuals done, no contradictions.** HIT-MV captures vs `ref/HIT-MV_jp.pdf`
  (H/M/D/B rules, limits, busy→NG). ELL14 vs Thorlabs' ELLO driver source (installed with ELLO;
  the ELLx manual PDF could not be downloaded automatically). Fixed stale lines in protocols.md;
  noted the homing-speed "F fast, M/S near sensor" idea is an assumption; i1/i2 decoded.
- ELLx manual **Issue 12** added by user (`ref/etn032283-d03.pdf`) and compared with the capture:
  all commands/replies agree. New points: manual defines no terminator (CR aborts a partial
  command; `0x07` not mentioned); `st` should reply `GS`; **continuous jog (jog step 0) needs
  `sv` 50–70 % or the unit may overheat**; home offset is factory-set (ours 3.214°, must be > 0.7°);
  persistence of `so`/`sj` without `us` unknown. Details in protocols.md.
- **Step 0.4 done** (HIT-MV both axes + ELL14). **Phase 0 done** except MFF101 (not installed).
- DG645 added to the inventory (not installed); memo step 0.5 = revisit Phase 0 for MFF101 + DG645.

- **Phase 1 started** (user: proceed until actual movement is needed).
  - 1.1 Transport: `Transport` ABC (own RX buffer, `read_until`/`read_exact`, raw-byte debug
    log), `SerialTransport`, `FakeTransport` + `ScriptedResponder`. TCP can be added for the DG645
    by implementing 5 small methods. Tests ✅ (no loopback hardware available, skipped).
  - 1.2 Op-log: JSON Lines per day, fsync per line, survives a crash mid-line (tested). Fields
    changed from the plan: `event` (start/done/failed) and `exchanges` [[tx, rx], …] instead of
    single raw_tx/raw_rx; polling during waits is not logged.
  - 1.3 Driver base (`execute`, `@action(moves=…)`, `request_stop`) + `config.py`
    (port by USB serial; **no fallback to the COM number** if the serial is missing).
  - 1.4 ELL14 driver (all ELLO functions) and 1.6 HIT-MV driver (insert = `B:` fast homing +
    `H:`, retract = `D:` + relative `M:` as SGSample, only from position 0; `move_abs`, `stop`,
    `emergency_stop`, status). Simulators `HitMvSim`/`Ell14Sim`. Tests compare TX bytes with
    the captures. **49 tests pass**, ruff clean.
  - `scripts/status.py` (read-only) and `scripts/ctl.py` (one action; motion refused without
    `--allow-motion`).
  - **Read-only hardware run ✅ 20:55** (vendor software closed, nothing moved): both devices
    connect via USB serial lookup. **`?:B0` = `?:B1` = `50000,500000,200,250000`** → insert will send
    `B:n,50000,1000000,200,250000`. ELL14 position **−355.31°** (counter not wrapped; left there
    by the capture's Clean→Stop), velocity `gv` = 100 %. Recorded in protocols.md.

### 2026-11-17
- **ELL14 hardware validation (1.4), user-approved moves:**
  - Move 1 ✅ 11:03:48 `home ccw`: TX `0ho1<07>` → `0POFFFFFFFE` after 0.36 s (from −355.31° ≙ 4.69°),
    ends at −2 p = −0.005° (within ELLO's ±3 p). User checked physically.
  - User then allowed **free ELL14 motion tests** (restore the original state afterwards); HIT-MV
    moves still need permission each time.
  - Full test 11:05–11:06 (our driver, all ELLO functions) ✅: `ma` 10/45/90° within +2 p,
    readback OK; `fw`/`bw` ±1991 p; `mr` ±0.1°; `ho0` (0.98 s) and `ho1` (0.44 s); `sj`/`so` same values
    → `GS00`; `cm` → `GS09`, stopped after 6 s: **`st` replies `GS00` by itself** (1.9 s later, when
    the motion has stopped) → open question closed. Clean stopped at −355.32° (≈ where we found the
    mount, so that position came from the capture's Clean→Stop).
  - Restored: counter −141491 (original −141493, 2 p = 0.005°), jog step 5.0°, home offset 3.214°.
  - **1.4 ELL14 validated on hardware ✅** (`clean_and_optimize` not run: it rewrites motor tuning).
- **HIT-MV hardware validation (1.6), user-approved, user watching the mirror:**
  - H1 ✅ 11:08:53 mirror (axis 1) `insert`: `!:`/`Q:` ready at 30000000 → `?:B1` →
    **`B:1,50000,1000000,200,250000` → `OK`** → `H:,1,,,,,,` → `OK`; done after **32.0 s**
    (SGSample: 62 s); `Q:` `30000000,0` = exactly 0; `Q:S` `00,00,00`. Fast homing works.
  - H2 ✅ 11:10:00 mirror `retract`: ready at 0 → `D:1,100000,1000000,200` → `OK` →
    `M:,+30000000,,,,,,` → `OK`; done after **30.3 s**; `Q:` `30000000,30000000`, `Q:S` 00.
    Identical to SGSample. Both axes back to the normal (retracted) state.
  - H3 ✅ 11:12:33 stop during mirror insert: `L:,1,,,,,,` after 5.06 s → `Aborted`, stopped ≈ 9.9 mm
    real in. **Finding: `!:` said ready at once, but the stage drifted another 79860 units (0.16 mm
    real) while decelerating** → driver must wait for `Q:` to settle after a stop (fixed, see below).
  - H4 ✅ insert from 25037160: 27.1 s → exactly 0. H5 ✅ retract: 30.4 s → 30000000.
  - Mirror (axis 1) fully validated. Photodiode (axis 0, H6/H7) not yet — needs permission.
  - Driver fix after H3 (simulator-tested only, not yet on hardware): after `L:` the driver waits
    until `Q:` stops changing (`_wait_settled`); before any move it reads `Q:` twice and refuses if
    the axis is still moving. `HitMvSim` now coasts after `L:` like the real unit. 50 tests pass.
  - H6 ✅ 11:17:41 photodiode (axis 0) `insert` (new double-`Q:` ready check passed):
    `B:0,50000,1000000,200,250000` → `OK`, `H:1,,,,,,,` → `OK`; done after **31.9 s**; `Q:`
    `0,30000000`, `Q:S` 00.
  - H7 ✅ 11:18:43 photodiode `retract`: `D:0,100000,1000000,200` → `OK`, `M:+30000000,,,,,,,` → `OK`;
    done after **30.3 s**; `Q:` `30000000,30000000`, `Q:S` 00. **Both axes retracted (normal state).**
  - **1.6 HIT-MV validated on hardware ✅** (both axes insert/retract, stop).
  - H3b ✅ 11:2x repeat stop test on the mirror (user-approved) to confirm the settle fix: stop
    requested 5.0 s after start → `Aborted` returned **0.64 s later** (poll wait + `L:` + settle);
    position right after = 25219040 (≈ 9.6 mm real in) and **unchanged over the next 2 s** → fix
    works on hardware. Then insert 27.5 s → 0, retract 30.7 s → 30000000. Both axes retracted.
- **Phase 2 started.** User: **one tab per device, like Chrome tabs; new device = new tab; clean
  and easy** (recorded in design-document). Installed PySide6 6.12.0 + pytest-qt 4.5.0.
  - Built: `DeviceService` (worker thread per device), tabbed `MainWindow`, `HitMvPanel` (card per
    feedthrough: big state RETRACTED/INSERTED/PARTLY INSERTED/Inserting…, insertion bar, mm real,
    Insert (with confirm) / Retract), `Ell14Panel` (angle, go-to, rotate-by, step, home + direction,
    collapsed Maintenance: step size, home offset (confirm), clean, clean & optimize (confirm)),
    live operation history, operator field, `--sim` mode, launchers. Drivers got `snapshot()`
    (unlogged polling) and a `progress` callback (live position during 30 s moves).
  - Bugs found by GUI tests and fixed: (1) STOP wired to the worker-thread service was queued
    until the move ended → now called directly; (2) stop flag cleared at the start of `execute()`
    could swallow an early STOP → cleared before "busy" instead.
  - 55 tests pass (5 GUI tests on simulators), ruff clean. Screenshots checked offscreen.
  - **New requirement (user): HIT-MV axes 0 and 1 must never be inserted at the same time** —
    retract one before inserting the other; GUI disables the other axis's buttons while one is
    not retracted. Recorded as design F2a; enforced in driver + GUI (config `exclusive_axes`).
  - **GUI tested on real devices by the user ✅ (12:08–12:14, op-log `logs/oplog-2026-11-17.jsonl`):**
    mirror insert 32 s → retract STOPped after 6 s → insert from there 7 s → retract 31 s;
    photodiode insert 32 s → retract 31 s (all ended at exactly 0 / 30000000); ELL14 3× go-to 31°
    + home, jog ×7, ended 30.99°. User: "they work well". Not yet on hardware: **retract from a
    partial position** (user chose Insert after the STOP). Operator field was left at the Windows
    account name (`h2_laserroom_03`).
  - **ELL14 = half-wave plate for 355 nm before a PBS** (user) → energy control, option 2 chosen:
    "Laser energy (355 nm)" section: Save current angle as max energy (confirm; old → new in the
    log), Go to max / Go to min (= max + 45°), Set energy % (T = cos²(2·(θ − θ_max))), live
    "Now ≈ x % of max". Home offset stays factory. Saved in `config/saved_angles.json` (program-
    written; simulation uses `logs/sim/`). `energy.py` + 4 driver actions. 72 tests pass.
    Real max-energy angle saved by the user on hardware: **30.9877°** (2026-11-17 12:26,
    `config/saved_angles.json`, committed as lab state).
  - Display choices (changeable): ELL14 angle shown modulo 360° (raw counter in tooltip);
    HIT-MV position in real mm (0 = inserted, 60 = retracted).

  - **DG645 Phase 0.5 (paper only, unit not installed):** read the manual's remote chapter;
    full command set, syntax, channel numbering, error codes recorded in `docs/protocols.md`
    § DG645. Key facts: RS-232 9600 8N1 RTS/CTS (LAN: raw TCP 5025), `DLAY c,d,t` sets channel c
    = channel d + t seconds, `DLAY?c` → `"d,+t"`, set commands give no reply (errors via
    `LERR?`), 5 ps resolution, **remote changes are not saved at power-off**. Plan written
    (implementation-plan 1.6b). No code yet (record before code).

  - **MFF101 Phase 0.5:** user connected one flip mount and controlled it with Kinesis. Seen by
    Windows as "APT USB Device", serial **37011815**, D2XX (no COM port). User supplied the APT
    protocol manual (Issue 48) → `ref/Kinesis_apt_communications_protocol.pdf`; MFF message
    subset, framing, USB set-up, status bits recorded in `docs/protocols.md` § MFF101.
    First probe: device held open after Kinesis; user re-plugged USB → probe OK (model string
    "MFF002", fw 1.0.3). **Flip test (user-approved, unit not on the bench):** jog dir 1 →
    position 1 (bit 0x01), dir 2 → position 2 (bit 0x02), ≈0.4 s, moving bit 0x10 both ways,
    repeat jog = no-op, no MOVE_COMPLETED → poll. Unit 37011815: **position 2 = "insert"**
    (current), **position 1 = "retract"** (user). Restored to insert. User decisions: **both
    flip mounts on one tab, cards like the HIT-MV tab**; second unit connected ~tomorrow;
    DIG IO not wired. Plan in implementation-plan 1.5 (D2XX via ctypes).

  - **MFF101 step 1.5 + GUI done (user: "write the GUI"):** `D2xxTransport`, `drivers/mff.py`
    (identify, status, insert/retract, flash_led, get_transit_time), `MffSim`, config
    `[devices.flipmounts]` (unit flip1 = 37011815, insert_position 2), "Flip mounts" tab with one
    card per unit (Insert/Retract, Flash LED, offline card for an unplugged unit, no STOP).
    86 tests pass, ruff clean. **On hardware (user-approved, off the bench):** connect, retract
    0.44 s, retract again = no-op, insert 0.44 s, transit 500 ms, LED command; ends at insert.

  - **Transfer to another PC (user request):** `README.md` (devices, moving to a new PC, setup,
    running, checks, safety, config, troubleshooting, catch-up reading order) and `CLAUDE.md`
    (standing agent rules, which until now lived only in this PC's agent memory). Launchers now
    find conda in several usual install folders (tested: activation + import OK).
    Notes: `logs/` and `captures/` are git-ignored, so copy the folder, not only git; re-run
    `pip install -e ".[dev]"` on the new PC; flip mounts need `ftd2xx.dll` (FTDI CDM or Kinesis).

### 2026-11-18
- **Second flip mount connected (6 m USB cable): serial 37006391**, MFF002 fw 1.0.3. Roles (user):
  unit 1 37011815 = **355 nm blocker**, unit 2 37006391 = **820 nm blocker**, both position 2 =
  insert. Unit 2 not on the optical path yet → free to test (user).
- **Link stability (new `tools/mff_link_test.py`): stable.** Burst 2500 queries + 50 reopen
  cycles, 30-min soak 8665 queries, 2804 queries during 20 flips — all OK, 0 errors, ≤ 19 ms.
- **Unit 2 problem found and explained:** after "go to position 1" it reached position 1 and
  went back to 2 by itself. Cause: its **DIG IO 2 is configured as "input-goto"** (unit 1:
  output); nothing is wired (user). With DigIO2 set like unit 1 (RAM only, user-approved):
  20/20 flips OK. Original setting restored after the test → **unit 2 still bounces** until a
  permanent fix is chosen. Details in protocols.md § MFF101 Unit 2.
- First Kinesis change did not reach the device: Kinesis saved it as a PC-side override
  (`C:\ProgramData\Thorlabs\MotionControl\ThorlabsSettingsOverrides.xml`). **User then set DIG IO 2
  = output-at-position/level with "Persist Settings to the Device", re-plugged → stored in the
  device ✅**; flip test 20/20 OK (0.40 s).
- **Config: flip2 = "820 nm blocker" (37006391), flip1 renamed "355 nm blocker"**, both insert =
  position 2. Tests updated (86 pass). `scripts/ctl.py` now knows the `mff` type (was missing).
  **On hardware via our driver (13:36):** unit 2 retract 0.44 s, insert 0.44 s, insert again =
  "already there". Unit 1 found at **retract** — left there by the user's GUI on 2026-11-17
  19:15 (op-log); not touched.
- **HIT-MV Insert: confirmation dialog removed** (user: not needed; design F2b). Insert starts at
  once; interlock unchanged. New GUI test checks that no dialog opens. ELL14 maintenance
  confirmations (save max energy, home offset, clean) are kept.
- **DAQ merge (F8), step 1: old DAQ code read** (`DAQ_oldcode/`, untracked, 154 MB with zips).
  The PicoScopes and the camera are now connected to **this PC** (the plan said "DAQ PC").
  - `H2LaserDAQ/` (PicoScope, ~2.5k lines, no tests, no git here): PyQt5 + pyqtgraph, picosdk
    ctypes. One `threading.Thread` per scope (`H2LaserDigitizer`), block capture loop, ADC→mV,
    ROOT via uproot (tree `rawWave`, 10000 triggers/file, background writer), CSV of summed
    area every 100 triggers (continuous mode), queue → GUI at 10 Hz. Modes: *continuous*
    (multi-scope, trend + waveforms) and *snapshot* (1 scope, averaged waveform, area ± err,
    Pause/Freeze/Save CSV). Python-file configs (`config/*.py`, `DIGITIZER_CONFIGS`), TUI launcher.
    Models: 3405D (ps3000a, ser. JY926/0005: 212/820 nm DET10A2, Ext trigger) and 2204A
    (ps2000, ser. 12017/0359 NO cell, 12017/0366 H2 VUV PD, 12017/0137 laser-room PD).
    Area = plain sum × dt (no baseline subtraction).
  - `IDS-Camera/` (package `laserdaq`, ~7.4k lines, ~290 tests, own memory bank): PySide6 +
    pyqtgraph, `ids_peak` SDK. `CameraBase`/`IDSCamera`/`MockCamera`, `AcquisitionController`
    (daemon thread, back-pressure, settings written on the acquisition thread),
    `FrameRecorder` (BMP per frame + frames.csv, 25 Hz), offline BMP→ROOT, auto gain with ROI,
    hang watchdog, TOML configs. Known: camera link unstable (USB 2.0, drops after a few
    open/close cycles); its docs say `signal_stop()` must not call `KillWait()`, but the code
    does (discrepancy to check).
  - This PC (read-only check): Windows sees 2× PicoScope 2000, 1× PicoScope 3000, IDS
    U3-327xCP-C ser. **4110039161**; also a Newport "Picomotor Controller" (not in scope).
    `ps2000.dll`/`ps3000a.dll` only inside PicoScope 7 (not on PATH); IDS peak runtime installed
    (Python bindings come from PyPI). The `H2LaserControl` env has none of the DAQ packages.
- **Merge decisions (user):** PicoScope continuous tab + H2 VUV PD snapshot tab, keep running
  until explicitly stopped; camera tab = exact copy of the current GUI, no TUI; output formats
  unchanged; `DAQ_oldcode/` git-ignored. → design F8a–c, plan `memory-bank/merge-plan.md`.
- **M0 environment:** DAQ packages added to `pyproject.toml` and installed (picosdk 1.1,
  ids-peak 1.17 / ipl 1.18 / common 2.1, uproot 5.7.7, awkward 2.15, pyqtgraph 0.14,
  numpy 2.5.5, opencv 5.1, imageio 2.38). IDS SDK loads and lists the camera
  (4110039161, U3-327xCP-C, openable; not opened). picosdk fails "PicoSDK not found": the DLLs
  exist only in `C:\Program Files\Pico Technology\PicoScope 7 T&M Stable` (ps2000 3.0.146,
  ps3000a 2.1.150); with that folder on PATH both load (no scope opened). PicoSDK itself is
  not installed → user to choose (merge-plan open point 1).
- **User decisions:** PicoSDK installed; configs confirmed (continuous = monitor_2026A,
  snapshot = H2PD_261103); Start / Pause / Stop per tab, nothing starts at launch; data in
  `data/picoscope` and `data/camera`; history viewer dropped (design F8a, F8d).
- **M0 done:** picosdk loads `ps2000.dll` 3.0.152 / `ps3000a.dll` 2.2.160 from the PicoSDK
  `lib` folder (machine PATH; shells started earlier must re-read PATH).
- **M1 done (`tools/daq_probe.py`, read-only):** 3405D JY926/0005 (USB 3.0), 2204A 12017/0359 and
  12017/0366 (USB 2.0) all open/close fine, match the old configs. Camera 4110039161 fw
  3.80.26143 streams 5/5 frames at 5 fps, but **runs on a USB 2.0 link (60 MB/s)**: at the
  default 20 fps the first buffer came back incomplete. Probe bug on the way: numpy view of a
  freed IPL image → access violation while streaming; camera survived. Details in
  `docs/protocols.md` § DAQ devices.
- **User decisions:** Pause = acquisition pauses and display freezes (no separate display
  freeze); camera tab shows only a start page until Start, Close returns to it.
- **M2–M6 done in simulation** (merge-plan.md): `daq/picoscope/` (digitizer port, ROOT writer
  copied, virtual digitizer, `PicoSession`), `gui/daq/` (ScopeTab + ported plot views,
  CameraTab), `laserdaq/` camera package copied (3 files changed: config/output folders, mock
  fallback), `config/camera/*.toml` (output_dir data/camera), devices.toml DAQ entries,
  `tools/bmp_to_root.py`, app-wide debug log + fault log + hang watchdog.
  Bugs found on the way: own `_stop` attribute shadowed `Thread._stop` (join failed); old
  snapshot "Saved" timer touched a deleted label after closing; the close question used the
  static QMessageBox (blocked tests); our app style sheet made the camera sidebar overflow its
  fixed 276 px → general rules scoped to our widget classes (`style.OWN`).
  Tests: 292 passed, 21 skipped (18 real-camera tests gated by `H2_CAMERA_HW=1`, 3 need the
  old reference BMP); ruff clean. Nothing was run on the real scopes/camera in this step.
- **User feedback on the sim GUI (fixed):** camera sidebar cut off on the right (old fixed
  276 px too narrow for the Fusion style) → sized to its content's minimum width (also on
  show); scope tabs now show only a start page (scopes, data folder, Start) until Start and
  again after Stop / when every scope failed (error shown there); waveform views in a light
  theme matching the GUI (white plots, dark axes, darker channel colours). 293 passed.
- **Scope config drop-down** (user request): the 8 old digitizer configs converted to
  `config/picoscope/*.toml` (6 snapshot, 2 continuous); each scope tab's start page lists the
  files of its mode (default from devices.toml), describes the chosen one, ↺ re-reads the
  folder, invalid files are listed with the reason; locked while running; the op-log start
  entry names the config. 296 passed, ruff clean.
- **M7 hardware test, scope monitor tab (user clicks, real `H2LaserControl.bat`; triggers
  present, no laser):** both scopes open (3405D by serial; ps2000 enumeration found
  12017/0359 + 0366, opening took ~9 s), 25.0 Hz on all scopes, ROOT/CSV written in the old
  format (CSV one row per 100 triggers). VUV PD snapshot tab ran 16 s at 25 Hz.
  *Hardware test finding:* in the first monitor run the 3405D (DET10A2) returned
  `PICO_TIMEOUT` from `ps3000aGetValues` 21 s after Start: last good trigger 17:21:30.36,
  error 17:21:35.43, i.e. one readout stalled ~5 s on USB while triggers continued (NOCell
  recorded them) and nothing else in the program was busy. Second run (47 s) clean. Cause
  unknown (USB link/hub/power); the old code has the same call and would have crashed too
  (and stopped all scopes). **Fix:** a failed arm/readout (3405D status ≠ 0, ps2000 ≤ 0) now
  skips that waveform, re-arms, shows a ⚠ warning in the tab and counts it
  (`skipped_waveforms` in the op-log stop entry); 3 failures in a row → that scope ends with
  an error. 298 passed.
- **Hardware test: 3405D readout stalls, cause isolated (scripts, scratch output, GUI closed
  during B/C/old):**
  | run | scopes | driver DLLs | result |
  |---|---|---|---|
  | 2 | 3405D + 2204A (monitor_2026A), our code | SDK 2.2.160 | stalls 57 s after start, then every ~30 s (5 s each, PICO_TIMEOUT); NOT_RESPONDING after 2.7 min |
  | A | 3405D alone, our code | SDK | **clean**, 3 min, 4522 waveforms, no gap |
  | B | both, our code | PicoScope 7 (2.1.150) | NOT_RESPONDING 6 s after the 2204A started |
  | C | both, our code, one lock for both drivers | SDK | stalls every 30–50 s, then NOT_RESPONDING |
  | old | both, **old H2LaserDAQ code** unchanged | SDK | NOT_RESPONDING after ~1 min; old code then stops all scopes |
  The 2204A never missed a trigger. 3405D open status PICO_OK (own power supply, USB 3);
  after NOT_RESPONDING a fresh open works. Topology: 3405D behind a Genesys USB 3 hub
  (05E3:0626) on one xHCI root hub; both 2204A behind two cascaded Genesys USB 2 hubs
  (05E3:0610) on another root hub. **Conclusion: not our code, not the driver version, not
  concurrent SDK calls; the 3405D drops out on this PC's USB setup when a 2204A acquires at
  the same time.** Next: user to try other USB ports (3405D directly on the PC, 2204As
  elsewhere); where/how the old program ran without this.
  User: the old program ran on a different PC with different cabling. Data rates are tiny
  (3405D ≈ 100 kB/s, 2204A ≈ 50–100 kB/s at 25 Hz), so not a bandwidth problem.
- **Re-cabled (user): 3405D moved to the control-device hub** (VID 35D6 PID 2510), the
  2204As stay on the DAQ hub. *Hardware tests:* both monitor scopes 3 min: 4505 + 4309
  waveforms at 25.0 Hz, 0 skipped, no gaps. **Both tabs together 15 min** (monitor + VUV PD
  snapshot, i.e. both 2204A at once, with Pause 20 s at 5:00): 0 skipped, 0 errors, 25.0 Hz on
  all three; ROOT rotation every 10000 triggers works (files _0000–_0002); only gaps = the
  pause, plus one 1.06 s gap in H2PD 3 s before Stop (no readout failure reported; watch in
  long runs). → ps2000 with our per-DLL lock is fine for two 2204A in one process.
- **Safety net added:** after 3 failed readouts in a row the scope is closed and reopened (2 s
  wait) and the run continues in the same files, with the running CSV sums kept; 3 reconnects
  without one good waveform → that scope ends with an error. Op-log stop entry has
  `reconnects` and `skipped_waveforms`. 299 passed.
- Camera in the GUI (user, 17:22): opened, 33 s live view, 184/184 frames, closed cleanly.
  Capture and multi-shot run not yet tested.
- **Hardware test: camera + all scopes, 5 min** (user request: the 2204As share a hub with the
  camera). Camera free-run requested 18 fps, one open/close: 3132 frames = steady 10.3 fps,
  ~42 % of frame IDs skipped from the start, no errors, clean close. Scopes: 0 skipped, no
  gaps (25 Hz). Camera-alone baseline still to do (likely our RGB conversion is the limit,
  not the hub).
- **Hardware finding + fix: starting/stopping one 2204A tab blocked the other 2204A.** The
  ps2000 search-and-open (~7 s) and close_unit (~1 s) ran under the shared per-DLL lock, so
  the running NOCell scope lost 7 s of triggers when the VUV PD tab started and 1 s when it
  stopped (and the last H2PD waveform was stamped ~1 s late at stop). Fix: open/close have
  their own lock (`_OPEN_LOCKS`), readout keeps `_LOCKS`. Hardware test: monitor running,
  VUV PD tab started/stopped 4 times → NOCell 25.00 Hz, no gaps; no crash (ps2000 tolerates
  opening one unit while another reads out).
- **Motor test (3405D + VUV mirror) not run:** user allowed it this once without watching.
  Windows now lists the FTDI COM adapters by hub port instead of serial since the re-cabling
  at 18:27 (pyserial serial "7"/"6"; D2XX still reads DU0DFFMC = COM5, DP06TVEF = COM6), so
  `resolve_port` cannot find hitmv/ell14 by serial. ELL14 answers on COM6. **HIT-MV on COM5
  does not answer** read-only `?:N`, `?:V`, `Q:` (CTS active). Only read-only queries were
  sent; nothing moved. To check: HIT-MV controller power / RS-232 cable after re-cabling.
  Timeline: HIT-MV answered every poll 17:21–17:33 (GUI); nothing talked to it 17:33–19:15;
  first contact after the 18:27 re-cabling failed → started with the re-cabling.
- **User: the HIT-MV controller had power problems; rebooted.** HIT-MV adapter re-plugged too:
  back as COM4 with serial DU0DFFMCA (found by serial again). ELL14 adapter still COM6 without
  serial. *Hardware (read-only):* controller answers; **position counters reset to 0,0** (were
  30000000 / 0); speeds back to defaults; axis 0 Q:S bit 4. See docs/protocols.md. The
  photodiode now reads INSERTED while it is (last known) retracted: its Retract would drive
  +60 mm into the limit → must be homed (H:) first, with the user's OK. Motor test still open.
- User calibrated with HIT Sample (homing) and retracted both axes by eye (reboot clears the
  position information). **Hardware tests (user-authorized, this run only):**
  - *Camera + 2204As (+3405D)*: one camera open/close, 18 fps requested. Camera alone 60 s:
    10.5 fps, ~39 % frame IDs skipped; with all 3 scopes 4 min: 10.3 fps, ~43 % skipped, no
    errors → the hub is not the limit, our Python RGB conversion is (the user's GUI multi-shot
    at 5 fps, 17:23: frame IDs 168–177 consecutive, 200 ms apart). Scopes 25.00 Hz, 0 skipped,
    no gaps (also no stop-time gap any more → open-lock fix).
  - *3405D + VUV mirror* (3405D on the control hub with the HIT-MV adapter): precondition both
    RETRACTED 30000000; 2 cycles insert (32.3 / 32.2 s → 0) + retract (30.6 / 30.6 s →
    30000000), photodiode stayed RETRACTED, no alarms. 3405D 4114 waveforms at 24.99 Hz, NOCell
    25.00 Hz, 0 skipped, 0 reconnects, no gaps.
  - Camera Capture + multi-shot were already done by the user in the GUI at 17:23 (OK).
  Test data deleted afterwards (user request): data/ and scratch runs.
  **M7 scope + camera acceptance on hardware: done.** Open: ELL14 adapter (COM6) has no
  serial in Windows since the re-cabling; HIT-MV power-cut detection (both axes 0) proposed.
- User: rotation mount back on COM3 (serial found), connected OK. Long GUI run: not needed now.
- **F2c HIT-MV "positions lost" lock** (user OK): all axes at 0 under the interlock ⇒ driver
  refuses insert/retract/move_abs with a plain message, snapshot has `positions_lost`, tab
  shows red "POSITION UNKNOWN" and disables the buttons. The old test "retract allowed when
  both read 0" now uses (0, partly inserted). README troubleshooting updated. 301 passed.
- Next: user's changes to the waveform display.
- **Waveform display changes 1+2 (F8e, F8f), sim-tested:** trigger channels (= each
  digitizer's `trigger_channel`: NOCell "Trig", H2PD "Trig"; 3405D uses Ext) are not plotted,
  in both views; files unchanged. Trigger rate per scope in each view's status row (removed
  from the tab header). Monitor: "Show last" drop-down (10 min … 14 days, default 5 hr, kept
  between runs) + "Latest" (follow newest after zoom/pan). History from the daily CSV files
  via new `daq/picoscope/history.py` (rows selected by timestamp, one extra day read because
  the CSV date switch happens only at a new ROOT file; half-written lines skipped; past files
  cached by mtime/size). Plots use peak downsampling + clip-to-view. Timing (synthetic 14 days,
  one row / 4 s, 302k rows/channel): first load 1.3 s, cached 0.02 s, redraw 0.25 s, live update
  ~0.1 s. 307 passed. Next: user checks in the simulation; then change 3 (snapshot).
- **Snapshot change 3 (F8g), sim-tested:** the digitizer now posts every waveform in snapshot
  mode (`{device, t, dt, Ch*}`; ROOT unchanged; the old 100-trigger averaging in the digitizer
  is gone). New `daq/picoscope/averaging.py` (`WaveAverager`: running sums over the last N or
  all since Clear (∞), Welford for ∞, re-sum every 4096 adds; per-waveform offset = mean of
  the first 5 % of the points, area = Σ(w − offset)·dt·1e-3 nV·s; sample std, stderr =
  std/√N). View: ▼ N ▲ (1…1024, ∞; a change restarts), Clear, statistics box (pg.TextItem in
  the signal plot's top-right), Freeze/Unfreeze + Math, Save. Tab poll 100 → 40 ms; GUI test at
  25 Hz triggers: > 15 fps redraws (≈ one per waveform). Default N = refresh_trigger_cnt
  rounded to a power of 2 (100 → 128); N kept between runs. Snapshot CSV: same layout + one
  `# Offset` comment line; its area is now offset-subtracted. 316 passed.
- Stats box larger (16 pt, bold values; user).
- **User: "a few seconds until the waveform appears" in snapshot mode.** From the log
  (hardware): Start 22:08:00.2 → H2PD open 22:08:11.8 = 11.6 s; the monitor's NOCell also
  11.6 s (3405D by serial: 3 s). Cause: ps2000 has no open-by-serial; the search opened every
  free 2204A (~4 s each) plus a final "no more units" call. Change: the search stops as soon as
  our serial is open (expected NOCell ~4 s, H2PD ~8 s since 0359 enumerates first); each
  open/close call is now timed in the debug log. ✅ *Hardware test (scripts, GUI scopes idle):*
  `ps2000_open_unit` = 3.5 s per unit, `ps2000_close_unit` = 1.1 s. H2PD alone: opens 0359,
  then 0366, closes 0359 → 8.1 s (was 11.6 s). Monitor: NOCell 3.5 s (was 11.6 s; the
  3405D opens in parallel). H2PD while the monitor runs (0359 busy): 3.5 s. No errors, 0
  skipped. Test data deleted.
- Start-page description updated for the new display (user). **Snapshot refresh rate on
  hardware** (real ScopeTab + H2PD, offscreen, 20 s): poll 40 ms → 20.9 redraws/s at 25.0 Hz
  triggers (timer jitter puts 2 waveforms in one poll); poll 20 ms → **25.0 redraws/s**, one
  per trigger. POLL_MS = 20. (On-screen painting not measured; 1000-point curves are cheap.)
- **Monitor live waveforms (right panel) refreshed per trigger** (user): continuous-mode
  digitizers also post every waveform (`{device, t, dt, waves: {channel name: mV}}`); the view
  keeps a sliding average of the last 100 per scope (`WaveAverager`, trigger channel left out)
  and redraws per poll. Trend points / CSV rows unchanged (per 100 triggers). Hardware (real
  ScopeTab, 3405D + NOCell, 20 s): 36.5 redraws/s total = each scope ~25/s (the two scopes'
  triggers arrive at different phases). Before: one redraw per 100 triggers (4 s). 317 passed.
- **User: the rotation mount always fails to connect at program start (Connect later works).**
  Log: `COM3 … PermissionError 13 Access is denied` at 22:42:37.088, while the flip mounts
  (D2XX) opened at 37.344, all devices connecting in parallel. *Hardware test (open/close
  only):* during each D2XX `FT_OpenEx(flip serial)` (~130 ms) opening COM3 fails with Access
  denied (74/95 attempts) → FT_OpenEx briefly opens every FTDI chip (ELL14 and HIT-MV adapters
  are FTDI FT230X). Fix: `transport.base.USB_OPEN_LOCK` around serial opens and FT_OpenEx, plus
  one retry after 0.5 s on "Access is denied". *Hardware:* ELL14 + HIT-MV + flip mounts connected
  in parallel 10×: old code 1 failure, with the lock 0 (with and without retry). 317 passed.

### 2026-11-19
- **Project moved** from `Desktop\H2LaserControl` to `C:\Users\h2_laserroom_03\H2LaserControl`
  (user). Editable install re-linked (`pip install -e .`), Desktop shortcut "H2 Laser Control"
  → `H2LaserControl.bat`. 317 passed in the new folder. The old Desktop copy still exists
  (identical; user to delete).
- **Two-level tabs (user):** top tabs **Control** (VUV feedthroughs, rotation mount, flip
  mounts; DG645 later) and **DAQ** (scope monitor, VUV PD snapshot, camera), each with one
  sub-tab per device. The group is chosen by device type (DAQ_TABS → DAQ, PANELS → Control),
  so a DG645 panel lands in Control automatically. The group tab's dot shows the most important
  state in it (error > busy > ok > off), so an error is visible while the other group is shown.
  Last group and sub-tabs are remembered. 318 passed.
- **Dark theme (user):** the whole program (control tabs, scope plots, camera window, history)
  follows the Windows light/dark setting, also when it is switched while running; dark colours =
  the old H2LaserDAQ monitor (Catppuccin Mocha). Light look unchanged. Scope views recolour in
  place (acquisition, averages and Freeze kept). Checked by screenshots of every tab in both
  themes (simulation, scopes running, camera open). Tests: switch while connected; switch while
  the snapshot runs. Test note: the `themes` fixture (tests/conftest.py) restores the app (no
  style sheet), because the camera sidebar test relies on it (test windows are never shown, so
  the sidebar is not re-fitted after a style-sheet change; in the program it fits, 548 ≥ 530 px).
  320 passed.
- **Window 4:3 at start (user):** as large as fits (90 % of the free screen height or width),
  centred; on this PC's 1920×1200 screen 1440×1080 (was a fixed 1100×780). 321 passed.
- **Dark colours changed (user: "don't like this purple-blue", wants ordinary mac-like dark):**
  neutral greys (window #282828, fields/plots #1e1e1e, buttons #3c3c3c, text #e5e5e5) and
  Apple's dark-mode system colours (green #30d158, orange #ff9f0a, red #ff453a, blue #0a84ff;
  channels in the same order as the light theme). Light theme unchanged.

## Open questions
- Flip mounts DIG IO (optional): should our driver also check MFF_OPERPARAMS at connect and warn
  (or set RAM-only) if a DIG IO pin is an input while nothing is wired? Protects against a
  replacement unit with the same factory setting.
- MFF101 second unit: serial and position ↔ name (tomorrow). What does each flip mount do in
  the beam path (for Phase 3 interlock rules with the feedthroughs)?
- DG645 (before coding): which channel (A–H), and its reference (T0 or another channel)? Typical
  value, allowed min/max, display unit and step sizes? Keep the value over power-off (`*SAV`)
  or not? Is cutting one pulse cycle short when the delay changes acceptable? RS-232 cable /
  USB adapter to be used?
- ~~Retract: relative `M:` or absolute `A:`?~~ **Decided (user, 2026-11-17): retract must also
  work after a stop halfway.** Retract = `D:` + relative `M:+(retracted − current)`: identical to
  SGSample's `M:+30000000` from 0, and from a partial position it moves out by the remaining
  distance. ⏳ Retract from a partial position not yet run on hardware (needs permission).
- ELL14: send the `0x07` terminator like ELLO, or none as the manual specifies? Both work.
  *Current code:* `0x07` (config `terminator`), works on hardware.
- ELL14 position counter can be outside 0–360° (now −355.31°). Show it modulo 360 in the GUI?
  `ma` to 0–360° from there turns the long way (harmless; homing resets the counter).
- ELL14 GUI: allow continuous jog (jog step 0)? If yes, must set `sv` 50–70 % first (overheating).
- ELL14 GUI: allow "Set Home Offset" for normal users? (factory value 3.214°, must be > 0.7°)

## Next step
- **DAQ merge (F8): user checks the simulated GUI** (`H2LaserControl-simulation.bat`), then
  M7 hardware test with the user: each scope tab on the real scopes (files compared with old
  program files), both 2204A tabs together, camera open / capture / multi-shot / close.
  Open: output names, camera USB 3 (merge-plan.md).
- DG645: answer the open questions → write driver + simulator + GUI tab (1.6b, can be done
  before installation against `Dg645Sim`) → hardware checks in `docs/protocols.md` once installed.
- MFF101 second unit (expected 2026-11-18): read serial (Windows device list), short flip test,
  add `[devices.flipmounts.units.flip2]` (label, usb_serial, insert_position). User to try the
  Flip mounts tab on the real unit; names/labels of the two flip mounts.
- Phase 1 remainder (1.5, 1.6b, 1.7) waits for MFF101/DG645 installation.
- Phase 2 finish: retract from a partial position on hardware (Insert → STOP → Retract);
  save the real max-energy angle and try the energy buttons on hardware; a non-developer lab
  member operates the GUI without help; open: require an operator name at start-up?
- Phase 3: write down the full interlock rule list with the user (most rules need the MFF101).
