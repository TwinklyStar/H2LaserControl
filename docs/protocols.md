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
- Distances in **0.01 µm units** per the manual (integer only; decimals → `NG`). `+` sign optional.
  ⚠ **On our feedthroughs this nominal unit is wrong by ×5** — see "Real scale" below. All values
  in this file are raw controller units unless marked "real".

### Real scale of our feedthroughs ✅ (user, 2026-11-16)
**30,000,000 controller units = 60 mm real travel** → **1 unit = 2 nm** (= 0.002 µm), i.e. real
distances/speeds are the nominal (0.01 µm-based) values **÷ 5**. The controller's `?:P` (0.10 µm/pulse)
does not match the actual stage pitch. Always command in controller units; convert only for display.
| Raw value | Nominal (manual) | **Real** |
|---|---|---|
| 30000000 (retracted) | 300 mm | **60 mm** |
| speed F 1000000 | 10 mm/s | **2 mm/s** |
| speed S 100000 | 1 mm/s | **0.2 mm/s** |
| homing F 500000 | 5 mm/s | **≈1 mm/s** |
| overshoot −49800 | −0.5 mm | **≈ −0.1 mm** |
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

### Read-only probe of our unit ✅ (2026-11-16, `tools/probe_readonly.py`)
| Query | Reply | Meaning |
|---|---|---|
| `?:N` | `HIT-MV    ` | name, **right-padded with spaces** → strip replies |
| `?:V` | `V1.20-001` | firmware |
| `?:Z` | `1` | **HIT mode** active |
| `Q:` | `30000000,30000000,,,,,,` | axes **0 and 1** connected, both at 30000000 (= 60 mm real, retracted); axes 2–7 not connected |
| `Q:S` | `00,00,00,,,,,,` | last command OK; axes 0/1: no limit, no alarm |
| `!:` | `0,0,,,,,,` | both ready |
| `?:P` | `0.10,…` | 0.10 µm per pulse (all axes) |
| `?:S` | `20,…` | microstep divide 20 |

Works at **38400 baud, 8N1, RTS/CTS**, CR+LF both ways (factory defaults).
Note: `?:P`/`?:S` list all 8 slots even for unconnected axes; `Q:` leaves them empty.

### Axis mapping (from user, 2026-11-16)
- Axis 0 = VUV photodiode feedthrough, axis 1 = 45° VUV mirror feedthrough (VUV diagnostic chamber).
- Retracted = 30000000 (60 mm real), inserted = 0. Normal state: both retracted.

### Insert = ORG (mechanical origin return)
User confirmed: in SGSample the **ORG button is used to insert** devices (origin = 0 mm = inserted
end). Homing every time removes drift over repeats, because the physical origin never changes.
⇒ INSERT = `H:` on that axis (not `A:0`); RETRACT = absolute move to 30000000 (to be confirmed).
⚠ Any `H:` on an axis inserts that device into the beam.

### Vendor software
SGSample (`C:\Program Files (x86)\SIGMA-KOKI\SGSample\`), HIT program = `HITSample.exe` (.NET).
Strings embedded in it match the manual's HIT-mode commands: `?:N ?:V ?:Z ?:P ?:S ?:D H: M: A: R:
L: L:E Q: Q:S !: D: Z:0 Z:1` and handshake options `RTS/CTS`, `RTS/Xonoff`.

### SGSample capture — connect & idle 🔍 (2026-11-16, `captures/hitmv_table.txt`, `tools/parse_spm_table.py`)
Port setup on open: 38400 baud (`00 96 00 00`), 8N1 (`00 00 08`), handshake = CTS handshake +
RTS handshake (RTS/CTS), DTR on, EOF char 0x1A. Matches our probe settings.

Connect sequence:
```
?:N  -> HIT-MV            ?:Z -> 1 (HIT mode)
then for each axis n = 0..7:  ?:Dn, ?:S, Q:, !:, Q:S
F:MU -> memory-switch dump (multi-chunk reply, terminated by 0x1A, not CR LF)
```
Speed settings `?:Dn` (S start, F max in units/s, R accel ms):
- axes 0, 1: `100000,1000000,200` → real 0.2 mm/s start, **2 mm/s max**, 200 ms ramp
  (60 mm stroke ≈ 30 s per move)
- axes 2–7: `10000,100000,200` (unused)

Idle: SGSample polls `Q:` ≈ 2×/s (plus very frequent `IOCTL_SERIAL_GET_COMMSTATUS`, which bloats
the monitor log; disable "Device Control" capture for long recordings).

### SGSample capture — mirror insert + retract 🔍 (2026-11-16 18:51, user-approved motion)
Compact log: `docs/captures/2026-11-16_hitmv_mirror_insert_retract.txt`
(raw: `captures/2026-11-16_hitmv_mirror_insert_retract_table.txt`, not in git).
User operation: ORG on mirror → wait → retract mirror. Mirror motion checked physically by user.

```
18:51:55  H:,1,,,,,,                 -> OK     INSERT (ORG, axis 1 only)
          ... Q:/!: polling ~30 Hz, axis 1 busy, ~1 mm/s real ...
18:52:56  overshoot past origin to -49800 (≈ -0.1 mm real), reverse, settle
18:52:57  Q: 30000000,0    !: 0,0              insert done (62 s)
18:53:07  D:1,100000,1000000,200     -> OK     set axis-1 speed (real S 0.2 mm/s, F 2 mm/s, R 200 ms)
18:53:07  M:,+30000000,,,,,,         -> OK     RETRACT = RELATIVE move +30000000 (60 mm real)
18:53:37  Q: 30000000,30000000  !: 0,0         retract done (30 s)
18:53:37  ?:D1                       -> 100000,1000000,200
```

Confirmed operations (axis 1 = mirror; axis 0 = photodiode presumably the same with p0):
| Operation | Command(s) | Duration | Done when |
|---|---|---|---|
| **INSERT** | `H:,1,,,,,,` | ≈ 62 s (homing ≈ 1 mm/s real + overshoot/return) | `!:` axis = 0 and `Q:` axis = 0 |
| **RETRACT** | `D:1,100000,1000000,200` then `M:,+30000000,,,,,,` | ≈ 30 s (2 mm/s real) | `!:` axis = 0 and `Q:` axis = 30000000 |

Notes:
- Command format: all 8 slots written (`H:,1,,,,,,` = 7 commas); empty slot = no operation.
- **Retract is relative (`M:` +30000000 = +60 mm real), not absolute.** It relies on the insert
  having homed to exactly 0. If retract is issued from any other position it won't end at 30000000. (Our driver
  should consider an absolute `A:,30000000` or check position first — decide in Phase 1.)
- SGSample sets the speed (`D:`) before the relative move, with the same values already stored.
- Homing speed (≈ 1 mm/s real) matches `50000,500000` values in the `F:MU` dump (origin-return S/F).
- During motion: tight `Q:` + `!:` polling (~30 Hz); idle: `Q:` ~2 Hz. No `NG`, no unanswered
  commands, `Q:S` status stayed `00` (no limit/alarm).

### Homing speed command `B` 📖 (manual 4-1-21)
`B:axis,s,f,r,m` — set origin-return speed of ONE axis: s start, f max, m intermediate (units/s),
r accel (ms); requires **s ≤ m ≤ f**; `NG` if the axis is busy. Read back with `?:B<axis>` →
`s,f,r,m` (manual example `1000,500000,100,200000`). Max output 800000 pulse/s (F 1000000 units/s
≈ 100000 pulse/s here → OK). Homing travels at F and approaches the sensor at M/S, so raising
only F should not change origin repeatability.
Current values on our unit: **not yet read** (`?:B0`, `?:B1` — read-only, do before changing).
Unknown: whether `B` is volatile (lost at power-off) or persists like a memory switch.

### Planned change: faster homing (user request, 2026-11-16) — ⏳ to implement in Phase 1
- Our software sets homing **F = 1000000** units/s (2 mm/s real, same as the retract speed) for
  the feedthrough axes; keep S, R, M unchanged → insert ≈ 30 s instead of ≈ 62 s.
- Send `B:` right before each `H:` (like SGSample sends `D:` before `M:`), so it does not depend
  on whether `B` persists, and SGSample behaviour is unaffected if it is used again.
- Verify on hardware (with user permission): insert time, final position exactly 0, overshoot
  past the origin still acceptable (was ≈ 0.1 mm real at the slower speed).

**SGSample "timeout" popup explained:** polling pauses for 2 s at 18:52:25 — exactly **30 s after
`H:`** — while the homing takes 62 s. SGSample evidently uses a fixed ~30 s motion timeout; the
controller never failed to reply and the move completed. Not a device problem. Our driver must use
per-operation timeouts (e.g. insert ≥ 90 s, retract ≥ 45 s).

### Still to verify (capture of vendor software)
- Exact commands for insert/retract (absolute `A:` vs relative `M:`; speed `D:` set beforehand?).
- Whether the vendor software sends anything at connect (mode switch, init) and how it polls.
- Which commands the vendor software sends for "insert"/"retract".
- Whether the vendor software changes speed (`D:`) before moves.

---

## Thorlabs ELL14 (COM3) — Elliptec rotation mount

Source: Thorlabs *ELLx modules protocol manual* (Issue 10). 📖 (to verify)
- 9600 baud, 8N1, no flow control; ASCII; multidrop address `0`–`F` (default `0`).
- Packet: `<addr><cmd>[data]`, data as uppercase ASCII hex; replies end with CR LF.
- Planned subset: `in` (info, incl. pulses/rev), `gs` (status/error), `ho0` (home),
  `ma<8 hex>` (move absolute), `gp` (get position). Replies: `IN…`, `GS…`, `PO…`.
- Commands are sent **without** terminator; replies end with CR LF. ✅

### Read-only probe of our unit ✅ (2026-11-16)
| Query | Reply |
|---|---|
| `0in` | `0IN0E1140112420251801016800023000` |
| `0gs` | `0GS00` → status 0 = OK, no error |
| `0gp` | `0PO00003040` → 0x3040 = 12352 pulses ≈ **31.02°** |

`IN` reply decoded: type `0E` (=14, ELL14) · serial `11401124` · year `2025` · firmware `18` ·
hardware `01` · travel `0168` (=360°) · pulses per travel `00023000` (=143 360 → 398.2 pulses/°).

---

## Thorlabs MFF101/M (×2, not installed yet) — flip mount

Source: Thorlabs *APT Communications Protocol*. 📖 (to verify)
- FTDI USB device; 115200 baud, 8N1, RTS/CTS. Binary: 6-byte header (msg id LE, params, dest, src),
  optional data packet.
- Planned subset: `MGMSG_HW_REQ_INFO`, `MGMSG_MOT_MOVE_JOG` (direction 1/2 = position 1/2),
  `MGMSG_MOT_REQ_STATUSBITS` / `GET_STATUSBITS`.
- Access options: pyserial after enabling VCP, `ftd2xx`, or Thorlabs Kinesis .NET via `pythonnet`.
