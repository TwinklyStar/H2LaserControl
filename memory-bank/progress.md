# Progress

## Current status
- **Phase 0 — nearly done.** 0.1 ✅, 0.2 ✅, 0.3 ✅ (HIT-MV/ELL14; MFF101 later),
  0.4 ✅ for HIT-MV (mirror insert/retract captured), ELL14 capture pending. No driver code yet.

## Device inventory
| Device | Qty | Port | FTDI serial | Status |
|---|---|---|---|---|
| Thorlabs ELL14 | 1 | COM3 | DP06TVEF | connected |
| Sigma Koki HIT-MV (2 linear feedthroughs) | 1 | COM4 (RS-232→USB adapter) | DU0DFFMC | connected |
| Thorlabs MFF101/M | 2 | — | — | **not installed yet** (future) |

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
- **HIT-MV part of step 0.4 done.** Photodiode (axis 0) assumed identical with p0 — not captured.

- Capture tool: Eltima / Electronic Team **Serial Port Monitor 9.5.602** (user-installed,
  signatures valid, sniffer driver `SPSniff`). HHD installer discarded (unverified signer).

- **User requirement recorded:** homing F = 1000000 units/s (via `B:` before `H:`, S/R/M kept).
  In implementation-plan 1.6, design-document F2, protocols.md. Read `?:B0/?:B1` first.

## Open questions
- Retract in our driver: replicate relative `M:` exactly, or use absolute `A:,30000000`?
- ELL14 capture with ELLO (step 0.4 for ELL14) — which operations does the user actually use?

## Next step
- 0.4 for ELL14: capture ELLO operations (needs user's go-ahead for any rotation).
- Then Phase 1: 1.1 transport layer → 1.2 operation log → 1.3 driver base/config.
