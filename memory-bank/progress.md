# Progress

## Current status
- **Phase 0 — done** (MFF101 parts deferred until installed). 0.1 ✅, 0.2 ✅, 0.3 ✅, 0.4 ✅
  (HIT-MV both axes, ELL14 all ELLO functions). No driver code yet. Next: Phase 1.

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

## Open questions
- Retract in our driver: replicate relative `M:` exactly, or use absolute `A:,30000000`?
- ELL14: send the `0x07` terminator like ELLO, or none as the manual specifies? Both work.
- ELL14 `st` reply: manual says `GS`; capture showed one `GS00` for `st`+`gs`. Check in Phase 1.
- ELL14 GUI: allow continuous jog (jog step 0)? If yes, must set `sv` 50–70 % first (overheating).
- ELL14 GUI: allow "Set Home Offset" for normal users? (factory value 3.214°, must be > 0.7°)

## Next step
- ⚠ **Memo:** go back to Phase 0 (step 0.5) for **MFF101 ×2** and **DG645** once they are
  installed (DG645: RS-232 now, maybe LAN later; manual from printed p. 41).
- Phase 1: 1.1 transport layer → 1.2 operation log → 1.3 driver base/config.
