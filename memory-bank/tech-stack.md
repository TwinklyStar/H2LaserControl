# Tech Stack

Guiding principle: **few, boring, well-supported dependencies.** The device protocols are
small; we implement our own thin drivers and use existing libraries as references.

## Runtime
| Item | Choice | Notes |
|---|---|---|
| OS | Windows 11 (single lab PC) | |
| Python | conda env **`H2LaserControl`**, **Python 3.12** | Chosen for broad wheel support (PySide6, ftd2xx, pythonnet) |
| Package layout | `src/h2lasercontrol/` + `pyproject.toml` (editable install `pip install -e .`) | |

## Libraries
| Purpose | Choice | Why |
|---|---|---|
| Serial I/O | **pyserial** | De-facto standard; works for all FTDI virtual COM ports |
| FTDI direct (fallback for MFF101) | **ftd2xx** (D2XX wrapper) | Only if the MFF101 is not exposed as a COM port (Thorlabs APT devices use the FTDI D2XX driver; VCP can be enabled in Device Manager → "Load VCP") |
| GUI (Phase 2) | **PySide6** 6.12 (Qt 6, LGPL) | Mature, native-looking, Qt Designer, signals/slots fit device threads |
| Config | **TOML** via stdlib `tomllib` (read) | Human-editable; named positions, ports, rules |
| Operation log | **JSON Lines** files (one per day) + stdlib `logging` for debug | Append-only, crash-safe, trivially parsed; can migrate to SQLite if querying becomes important |
| Testing | **pytest** + fake/simulated serial devices; **pytest-qt** for the GUI | Test drivers, GUI and rules without hardware (GUI tests: `QT_QPA_PLATFORM=offscreen`) |
| Lint/format | **ruff** | Single fast tool |
| VCS | **git** | |

## Protocol references (primary sources)
| Device | Protocol | Reference |
|---|---|---|
| ELL14 | ASCII, 9600 8N1, multidrop addresses `0`–`F`, data as ASCII hex | Thorlabs *ELLx modules protocol manual* Issue 12 → `ref/etn032283-d03.pdf`; ELLO driver source in `C:\Program Files\Thorlabs\Elliptec\Source Code\ELLO_DLL\` |
| MFF101/M | Thorlabs **APT** binary protocol (6-byte header + optional data), 115200 8N1, RTS/CTS | Thorlabs *APT Communications Protocol* PDF |
| HIT-MV | Sigma Koki HIT-mode command set (ASCII, CR+LF), 38400 8N1 RTS/CTS default | `ref/HIT-MV_jp.pdf`; summary in `docs/protocols.md` |

Reference implementations to cross-check against (not runtime dependencies):
`thorlabs_elliptec`, `tl_elliptec`, `thorlabs-apt-protocol`, `thorlabs-apt-device`, `pylablib`.

## Serial traffic capture (for verification)
| Situation | Tool |
|---|---|
| Vendor software opens a COM port (Elliptec ELLO, Sigma Koki) | Software port monitor (e.g. HHD *Free Serial Port Monitor*) **or** a com0com virtual pair + our own Python relay/logger script |
| Vendor software uses FTDI D2XX directly (Kinesis → MFF101) | COM-level sniffers can't see it; use **USBPcap + Wireshark**, or rely on the (well-documented) APT manual — preferred |

## Deliberately not used (for now)
- Vendor DLLs / .NET Kinesis SDK — heavy, harder to log every command, tied to vendor installs.
- Big frameworks (Qudi, Bluesky, EPICS) — overkill for 3 devices and a simple-user GUI.
