# Progress

## Current status
- **Phase 0 — in progress.** Steps 0.1 (partly) and 0.3 (HIT-MV part) done. No driver code yet.

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

## Open questions
- Git author name/email for commits.
- HIT-MV: actual baud/mode configured on our unit, axis numbers of the two feedthroughs.

## Next step
- 0.1: finish (pyproject.toml, package skeleton, first commit).
- 0.2: `tools/list_ports.py`; read-only probe of HIT-MV (`?:N`, `?:Z`, `Q:`, `!:`) and ELL14 (`0in`).
