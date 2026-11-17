# Progress

## Current status
- **Phase 0 — done** (MFF101 parts deferred until installed). 0.1 ✅, 0.2 ✅, 0.3 ✅, 0.4 ✅
  (HIT-MV both axes, ELL14 all ELLO functions).
- **Phase 1 — in progress.** 1.1 ✅, 1.2 ✅, 1.3 ✅ (2 devices; MFF101/DG645 not installed).
  **1.4 ELL14 ✅ and 1.6 HIT-MV ✅ validated on hardware** (2026-11-17, incl. post-stop settle fix).
- **Phase 2 — in progress** (started 2026-11-17). 2.1 services ✅, 2.2 tabbed main window ✅,
  2.3 history panel ✅, 2.4 startup/shutdown ✅, 2.5 launchers ✅ — all tested in **simulation**
  only. ⏳ Next: try with the real devices (user), then usability feedback. 1.5 MFF101 / 1.6b DG645 wait for 0.5 (not installed). 1.7 demo needs MFF101.

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
  - Display choices (changeable): ELL14 angle shown modulo 360° (raw counter in tooltip);
    HIT-MV position in real mm (0 = inserted, 60 = retracted).

## Open questions
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
- ⚠ **Memo:** go back to Phase 0 (step 0.5) for **MFF101 ×2** and **DG645** once they are
  installed (DG645: RS-232 now, maybe LAN later; manual from printed p. 41).
- Phase 1 remainder (1.5, 1.6b, 1.7) waits for MFF101/DG645 installation.
- Phase 2: user tries the GUI (simulation first, then real devices — any click that moves a
  HIT-MV feedthrough is the user's own action); collect feedback; then validate 2.x on hardware.
