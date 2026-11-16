# Device Protocols (command subset we use)

Status legend: 📖 from manual · 🔍 verified by capture · ✅ verified on hardware

---

## Sigma Koki HIT-MV (COM4, RS-232 via USB adapter)

Source: `ref/HIT-MV_jp.pdf` (HIT-MV / HIT-S / HIT-SH 取扱説明書, 2021-09), ch. 3-3-2, 4-1, 6-1.

### Port settings 📖
| Item | Value |
|---|---|
| Baud | 4800/9600/19200/**38400 (factory default)**/57600 — set by memory switch `Baudrate` |
| Format | 8 data bits, no parity, 1 stop bit |
| Flow control | **RTS/CTS hardware** (memory switch `RS232C_FLOW`, default ON) |
| Delimiter | **CR+LF** (both directions) |
| Interface memory switch | `INTERFACE` = RS232C (factory default) |

### Command modes 📖
Two command formats: **HIT mode** (up to 8 axes, used here) and SHOT mode (legacy).
Switch with `Z` command; query current mode with `?:Z` → `0` = SHOT, `1` = HIT.
To be confirmed which mode our unit / the vendor software uses.

### HIT-mode format 📖
`<code>:<p0>,<p1>,...,<p7>` CR LF
- `p0..p7` = parameter for slave (axis) number 0–7. Omit a parameter (keep the comma) for
  "no operation" on that axis; trailing parameters can be dropped.
- Distances in **0.01 µm units** (integer only; decimals → `NG`). `+` sign optional.
- Case-insensitive; **no leading/trailing spaces** (→ `NG`).
- Drive commands (H, M, A, E, K, J) start immediately — no `G:` needed (G is invalid in HIT mode).
- Reply: `OK` / `NG` for most commands; status data for `Q`, `!`, `?`, `I`.
- Sending any command except `Q ? L ! I O` to a **busy** axis → `NG`, whole command rejected.

### Commands we need 📖
| Purpose | Command | Example | Reply |
|---|---|---|---|
| Home (mechanical origin) | `H:p0,p1,...` (1 = home that axis) | `H:1,1` → home axes 0 and 1 | `OK`/`NG` |
| Absolute move | `A:p0,p1,...` (0.01 µm) | `A:,500000` → axis 1 to +5 mm | `OK`/`NG` |
| Relative move | `M:p0,p1,...` | `M:100000` → axis 0 +1 mm | `OK`/`NG` |
| Decelerate-stop | `L:p0,p1,...` (1 = stop) | `L:1,1` | `OK` |
| Emergency stop (all) | `L:E` | | `OK` |
| Position | `Q:` | | `-1000,1000,100,,,,0,0` (0.01 µm, empty = not connected) |
| Status | `Q:S` | | `stm,sts0,...,sts7` (stm `00` OK / `01` last cmd rejected; sts = hex bit field) |
| Busy/ready | `!:` | | `1,0,,,,,,` (1 = busy, 0 = ready, empty = not connected) |
| Device name | `?:N` | | `HIT-MV` |
| Version | `?:V` | | `V1.00-001` |
| Mode | `?:Z` | | `0` SHOT / `1` HIT |
| Speed settings | `?:D<axis>` / `D:axis,s,f,r` | `D:5,10000,100000,200` | |

`Q:S` slave status bits: 0 −LS, 1 +LS, 2 ORG, 3 Near, 4 Z-limit, 5 Scale alarm, 6 DRV alarm.

### To verify by capture / on hardware
- Actual baud rate & mode set on our unit; axis numbers of the two linear feedthroughs.
- Which commands the vendor software sends for "insert"/"retract".
- Whether the vendor software changes speed (`D:`) before moves.

---

## Thorlabs ELL14 (COM3) — Elliptec rotation mount

Source: Thorlabs *ELLx modules protocol manual* (Issue 10). 📖 (to verify)
- 9600 baud, 8N1, no flow control; ASCII; multidrop address `0`–`F` (default `0`).
- Packet: `<addr><cmd>[data]`, data as uppercase ASCII hex; replies end with CR LF.
- Planned subset: `in` (info, incl. pulses/rev), `gs` (status/error), `ho0` (home),
  `ma<8 hex>` (move absolute), `gp` (get position). Replies: `IN…`, `GS…`, `PO…`.

---

## Thorlabs MFF101/M (×2, not installed yet) — flip mount

Source: Thorlabs *APT Communications Protocol*. 📖 (to verify)
- FTDI USB device; 115200 baud, 8N1, RTS/CTS. Binary: 6-byte header (msg id LE, params, dest, src),
  optional data packet.
- Planned subset: `MGMSG_HW_REQ_INFO`, `MGMSG_MOT_MOVE_JOG` (direction 1/2 = position 1/2),
  `MGMSG_MOT_REQ_STATUSBITS` / `GET_STATUSBITS`.
- Access options: pyserial after enabling VCP, `ftd2xx`, or Thorlabs Kinesis .NET via `pythonnet`.
