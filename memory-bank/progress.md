# Progress

## Current status
- **Phase 0 — nearly done.** 0.1 ✅, 0.2 ✅, 0.3 ✅ for HIT-MV/ELL14 (MFF101 later), 0.4 optional.
  No driver code yet.

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
  First commit pending: git user.name/email not configured yet.
- HIT-MV manual (`ref/HIT-MV_jp.pdf`, Japanese) read: port settings (38400 default, 8N1,
  RTS/CTS, CR+LF) and HIT-mode command set summarized in `docs/protocols.md`.

- Git identity set (repo-local, author "Meng"). Package skeleton (`pyproject.toml`,
  `src/h2lasercontrol`, `tests/`), `tools/list_ports.py`, `tools/probe_readonly.py` added;
  editable install OK, pytest OK, ruff OK. First commit `cc9b7a5`. **Step 0.1 done.**
- pyserial reports FTDI serials with suffix `A`: COM3 = `DP06TVEFA`, COM4 = `DU0DFFMCA`.

- **Read-only probe succeeded** (vendor software closed), details in `docs/protocols.md`:
  - HIT-MV: 38400 8N1 RTS/CTS, firmware V1.20-001, **HIT mode**, axes **0 and 1** connected,
    both at 30000000 (=300.000 mm), ready, no alarms; 0.10 µm/pulse.
  - ELL14: serial 11401124, OK status, position 0x3040 ≈ 31.02°, 143360 pulses/360°.
  - Created `config/devices.toml` (ports by USB serial). **Step 0.2 done.**

## Open questions
- HIT-MV: which physical feedthrough is axis 0 / axis 1; is 300 mm currently IN or OUT?

## Next step
- 0.4 (short): capture what the Sigma Koki software sends for insert/retract (optional).
- Then Phase 1: 1.1 transport layer → 1.2 operation log → 1.3 driver base/config.
