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
Our unit and SGSample use **HIT mode** (`?:Z` → `1`, probe + capture).

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
⇒ INSERT = `H:` on that axis (not `A:0`); RETRACT = `D:` + **relative** `M:` +30000000 (confirmed
by capture, see below).
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

Confirmed operations (axis 1 = mirror; axis 0 = photodiode identical with p0 — captured 19:03, see below):
| Operation | Command(s) | Duration | Done when |
|---|---|---|---|
| **INSERT** | `H:,1,,,,,,` | ≈ 62 s (homing ≈ 1 mm/s real + overshoot/return) | `!:` axis = 0 and `Q:` axis = 0 |
| **RETRACT** | `D:1,100000,1000000,200` then `M:,+30000000,,,,,,` | ≈ 30 s (2 mm/s real) | `!:` axis = 0 and `Q:` axis = 30000000 |

Notes:
- Command format: all 8 slots written (`H:,1,,,,,,` = 7 commas); empty slot = no operation.
- **Retract is relative (`M:` +30000000 = +60 mm real), not absolute.** It relies on the insert
  having homed to exactly 0. If retract is issued from any other position it won't end at 30000000.
  **Our driver (decided 2026-11-17):** `M:+(30000000 − current position)` — same command as SGSample
  from 0; from a partial position (after STOP) it moves out by the remaining distance.
- SGSample sets the speed (`D:`) before the relative move, with the same values already stored.
- Homing speed (≈ 1 mm/s real) matches `50000,500000` values in the `F:MU` dump (origin-return S/F).
- During motion: tight `Q:` + `!:` polling (~30 Hz); idle: `Q:` ~2 Hz. No `NG`, no unanswered
  commands, `Q:S` status stayed `00` (no limit/alarm).

### SGSample capture — photodiode insert + retract 🔍 (2026-11-16 19:03, user-approved motion)
Compact log: `docs/captures/2026-11-16_hitmv_photodiode_insert_retract.txt`
(raw: `captures/2026-11-16_hitmv_photodiode_insert_retract_table.txt`, not in git).
```
19:03:07  H:1,,,,,,,                 -> OK     INSERT axis 0 (p0 = 1, then 7 commas)
19:04:09  !: 0,0   Q: 0,30000000               insert done (62 s)
19:04:20  D:0,100000,1000000,200     -> OK
19:04:20  M:+30000000,,,,,,,         -> OK     RETRACT axis 0, relative +30000000
19:04:50  !: 0,0   Q: 30000000,30000000        retract done (30 s)
19:04:50  ?:D0                       -> 100000,1000000,200
```
- **Axis 0 behaves exactly like axis 1** with the parameter in slot p0. Same durations, no `NG`,
  no unanswered commands, `Q:S` stayed `00`.
- Polling pause 19:03:38–19:03:45 (≈ 31 s after `H:`) = SGSample's timeout popup again.
- Homing turn-around differs between axes (observation only): axis 0 reversed at **+83920**
  (sensor reached *before* counter 0), axis 1 at **−49800** (after counter 0); both then approach
  slowly and settle at exactly 0. So before each homing the counter is off from the physical origin
  by roughly 0.1–0.2 mm real — consistent with the user's reason for homing on every insert
  (removes drift). Not yet understood in detail.

### Homing speed command `B` 📖 (manual 4-1-21)
`B:axis,s,f,r,m` — set origin-return speed of ONE axis: s start, f max, m intermediate (units/s),
r accel (ms); requires **s ≤ m ≤ f**; `NG` if the axis is busy. Read back with `?:B<axis>` →
`s,f,r,m` (manual example `1000,500000,100,200000`). Max output 800000 pulse/s (F 1000000 units/s
≈ 100000 pulse/s here → OK). *Assumption (not stated in the manual text; its homing diagrams
did not survive text extraction):* homing travels at F and approaches the sensor at M/S, so raising
only F should not change origin repeatability — to be confirmed on hardware.
Memory-switch defaults (manual 3-x): homing S 50000, F 500000, R 200, **M 250000**; ORG offset 0
(= 0.5 mm nominal = 50000 units). The `?:B` example `1000,500000,100,200000` in 4-1-17 is only an
example. Current values on our unit ✅ (read-only, 2026-11-16 20:55, `scripts/status.py`):
**`?:B0` = `?:B1` = `50000,500000,200,250000`** (s, f, r, m) = the memory-switch defaults. So our
insert sends `B:n,50000,1000000,200,250000` (only F changed; s ≤ m ≤ f holds).
Unknown: whether `B` is volatile (lost at power-off) or persists like a memory switch.

### Planned change: faster homing (user request, 2026-11-16) — ⏳ to implement in Phase 1
- Our software sets homing **F = 1000000** units/s (2 mm/s real, same as the retract speed) for
  the feedthrough axes; keep S, R, M unchanged → insert ≈ 30 s instead of ≈ 62 s.
- Send `B:` right before each `H:` (like SGSample sends `D:` before `M:`), so it does not depend
  on whether `B` persists, and SGSample behaviour is unaffected if it is used again.
- Verify on hardware (with user permission): insert time, final position exactly 0, overshoot
  past the origin still acceptable (was ≈ 0.1 mm real at the slower speed).
- ✅ **Hardware 2026-11-17 11:08 (mirror, axis 1, our driver):** `B:1,50000,1000000,200,250000` →
  `OK`, `H:,1,,,,,,` → `OK`, finished in **32.0 s** (was 62 s), ended at exactly **0**, `Q:S` 00.
  Overshoot not measured (driver polls only `!:` while waiting).

### Stop during a move ✅ (hardware 2026-11-17 11:12, mirror axis 1, fast homing, user-approved)
`L:,1,,,,,,` → `OK` sent 5.06 s after `H:`. The axis stopped ≈ 9.9 mm real into the travel.
⚠ **`!:` reported the axis ready (`0`) immediately after `L:`** (position 25117020), but 1 s later
`Q:` read **25037160** — it kept moving **79860 units (0.16 mm real)** while decelerating
(≈ ½ · 1000000 units/s · 200 ms ramp = 100000). ⇒ After a stop, `!:` = ready does **not** mean the
stage is standing still; wait until `Q:` stops changing before reporting "stopped" or sending the next
command. Homing from that position (H4) then took 27.1 s and ended at exactly 0; retract (H5) 30.4 s
→ 30000000. No alarms.
✅ Repeat with the settle fix (2026-11-17, mirror): `Aborted` returned 0.64 s after the stop request;
position 25219040 and **no further change over 2 s**. Driver behaviour confirmed.

**SGSample "timeout" popup explained:** polling pauses for 2 s at 18:52:25 — exactly **30 s after
`H:`** — while the homing takes 62 s. SGSample evidently uses a fixed ~30 s motion timeout; the
controller never failed to reply and the move completed. Not a device problem. Our driver must use
per-operation timeouts (e.g. insert ≥ 90 s, retract ≥ 45 s).

### Cross-check: captures vs. manual (2026-11-16) — no contradictions
| Captured | Manual rule | Result |
|---|---|---|
| `H:,1,,,,,,` / `H:1,,,,,,,` | 4-1-2: param 1 = home that axis; omitted = NOP; coordinate cleared to 0 | ✔ ends at exactly 0 |
| `M:+30000000,…` | 4-1-3: relative, `+` optional; limit ±134217727 **pulses** | ✔ 30000000 units ÷ 10 units/pulse (`?:P` 0.10 µm) = 3 000 000 pulses |
| `D:n,100000,1000000,200` | 4-1-11: one axis, s ≤ f, r 1–1000 ms, NG if busy; >800000 pulse/s clipped | ✔ F = 100 000 pulse/s; SGSample sends it only when the axis is ready |
| replies `OK`, `Q:`/`!:` data | 4-1-1, 4-1-14/16: OK/NG; Q values left-justified, variable length | ✔ (padding spaces = left-justified) |
| `Q:S` → `00,00,00` | 4-1-15: stm 00 = last cmd accepted, sts bits | ✔ |
| planned `B:n,s,f,r,m` | 4-1-21: one axis, **s ≤ m ≤ f**, NG if busy **or not connected** | ✔ plan respects it; send only when ready |

Notes from the check (not contradictions, but worth knowing):
- **Scale:** the manual's 0.01 µm/unit and `?:P` = 0.10 µm/pulse give 300 mm for 30000000; the
  real stroke is 60 mm (user). So the controller's stage parameters don't describe the real
  stage (factor 5). Harmless as long as we command raw units, but all manual "mm" values ÷ 5.
- **Homing overshoot hypothesis:** axis 1 turned at −49800 ≈ −50000 = the default ORG offset
  (0.5 mm nominal). Possibly the ORG-offset move of the homing method — unverified; homing method
  (`ORG SEL`) and offsets per axis are in the `F:MU` dump, not decoded yet.
- Manual 4-1-1: any command except `Q ? L ! I O` to a **busy** axis → NG and the *whole* line is
  rejected → our driver must check `!:` before `D:`/`B:`/`H:`/`M:`.

---

## Thorlabs ELL14 (COM3) — Elliptec rotation mount

Sources: Thorlabs *ELLx OEM/Bare modules protocol manual* **Issue 12 (July 2026)** =
`ref/etn032283-d03.pdf` (user-supplied), and **Thorlabs' own ELLO driver source** installed at
`C:\Program Files\Thorlabs\Elliptec\Source Code\ELLO_DLL\`. Comparison: see "Cross-check vs. manual".
- 9600 baud, 8N1, **no handshake**; ASCII; multidrop address `0`–`F` (default `0`). 📖✅
- Packet: `<addr><cmd>[data]`, data as uppercase ASCII hex; replies end with CR LF.
- Subset we use: see the ELLO table below (all panel functions). Home for our use = `ho1`.
- Commands work **without** terminator (our probe ✅) and with `0x07` (ELLO: `NewLine = "\a"` 📖🔍).

### Read-only probe of our unit ✅ (2026-11-16)
| Query | Reply |
|---|---|
| `0in` | `0IN0E1140112420251801016800023000` |
| `0gs` | `0GS00` → status 0 = OK, no error |
| `0gp` | `0PO00003040` → 0x3040 = 12352 pulses ≈ **31.02°** |

Second read-only check ✅ (2026-11-16 20:55, our driver via `scripts/status.py`, `0x07` terminator):
`0gs` → `GS00`, `0gp` → `0POFFFDD74B` = −141493 p = **−355.31°** (= 4.69° physically), `0go` →
`HO00000500`, `0gj` → `GJ000007C7`, **`0gv` → `GV64` = 100 % velocity**.
⇒ The position counter is **not wrapped to 0–360°**; it can be negative / beyond one turn (here
after the capture's Clean → Stop). Homing resets it to 0. (Display/`ma` handling: see progress.md.)

`IN` reply decoded: type `0E` (=14, ELL14) · serial `11401124` · year `2025` · firmware `18` ·
hardware `01` · travel `0168` (=360°) · pulses per travel `00023000` (=143 360 → 398.2 pulses/°).

### ELLO panel → operations we need (user: "all these functions are needed", 2026-11-16)
Values shown in ELLO for our unit: position 31.025°, **home offset 3.214°**, **home direction
anticlockwise**, **jog step 5.0°** (0.0 = continuous). Expected commands from the ELLx manual 📖 —
**all to be confirmed by capture** 🔍:

| ELLO control | Expected command(s) | Moves? | Writes to device? |
|---|---|---|---|
| Position → Update | `gp` → `PO` | no | no |
| Home (direction CW/CCW) | `ho0` / `ho1` → `PO` | **yes** | no |
| Home Offset Get / Set | `go` → `HO` / `so<hex>` | no | **yes** |
| Home Direction | (local choice of `ho0`/`ho1`?) | no | ? |
| Jog Step Get / Set | `gj` → `GJ` / `sj<hex>` | no | **yes** |
| Jog Backward / Forward | `bw` / `fw` → `PO` | **yes** | no |
| Move Absolute | `ma<8 hex>` → `PO` | **yes** | no |
| Move Relative | `mr<8 hex>` → `PO` | **yes** | no |
| Clean Device | `cm` (long, full-range motion) | **yes** | ? |
| Clean and Optimize | `om` (long; re-tunes motor frequencies) | **yes** | **yes** |
| Stop | `st` | stops | no |

### ELLO capture — all panel functions 🔍 (2026-11-16 20:18–20:20)
Compact log: `docs/captures/2026-11-16_ell14_ello_all_functions.txt`. Clean & Optimize not captured
(by choice). All expected commands **confirmed**, with these details:

- **ELLO ends every command with `0x07` (BEL)**, e.g. `30 69 6e 07` = `0in<BEL>`. Our probe sent
  no terminator and also worked → the device accepts both. Replies always end CR LF.
- Replies can arrive **split across reads** (e.g. `0` then `POFFFFFFFB\r\n`) → read until CR LF.
- **Connect sequence:** `0in`, then address scan `1in`…`Fin` (no reply, ~1 s timeout each),
  then `0i1`, `0i2` (motor info), `0go`, `0gj`, `0gp`.
- Data = 8 uppercase hex digits, **signed 32-bit two's complement** (`FFFFFFFB` = −5,
  `mrFFFFFFD8` = −40 pulses).

| ELLO control | TX (all + `<07>`) | RX | Notes |
|---|---|---|---|
| Update | `0gp` | `0PO00003043` | 12355 p = 31.025° |
| Home Offset Get | `0go` | `0HO00000500` | 1280 p = **3.214°** |
| Home Offset Set | `0so00000500` | `0GS00` | same value re-written |
| Jog Step Get | `0gj` | `0GJ000007C7` | 1991 p = **5.000°** |
| Jog Step Set | `0sj000007C7` | `0GS00` | same value re-written |
| Home Direction | — | — | **no traffic**: ELLO only remembers it, chooses `ho0`/`ho1` |
| Home (anticlockwise) | `0ho1` | `0PO00000000` | **`ho1` = CCW** (so `ho0` = CW); ~1 s from 31° |
| Forward | `0fw` | `0PO000007C4` | +1988 p = 4.992° (one jog step) |
| Backward | `0bw` | `0POFFFFFFFB` | −5 p = −0.013° |
| Move Absolute 31.025° | `0ma00003043` | `0PO00003044` | ELLO rounds deg → pulses |
| Move Relative +0.1° | `0mr00000028` | `0PO0000306A` | 40 p commanded, +38 actual |
| Move Relative −0.1° | `0mrFFFFFFD8` | `0PO00003045` | −40 p commanded, −37 actual |
| Clean Device | `0cm` | `0GS09` | immediate reply, **status 9 = busy** |
| Stop | `0st` then `0gs` | `0GS00` | only **one** `GS00` for the two commands — `st` reply ambiguous |

- Motion commands: the `PO` reply comes **when the motion is finished**; ELLO does not poll
  during motion. Repeatability: within ±3 pulses (≈ ±0.008°).
- `cm` (clean) answers `GS09` at once and runs in the background; after `st`, `gs` → `GS00`.
- `i1`/`i2` replies recorded raw (motor 1/2 info: frequencies etc.), decoded below.

### Our driver on hardware ✅ (2026-11-17 11:05, `0x07` terminator, all functions except `om`)
| Command | Reply | Notes |
|---|---|---|
| `0ma00000F8E` / `00004600` / `00008C00` (10/45/90°) | `PO…F90` / `…4601` / `…8C00` | within +2 p; 0.2–0.34 s |
| `0fw` / `0bw` | `PO000093C8` / `PO00008C04` | ±1991 p (5°) |
| `0mr00000028` / `0mrFFFFFFD8` | `PO00008C2A` / `PO00008C06` | ±0.1° |
| `0ho0` (CW) / `0ho1` (CCW) | `PO00000003` / `PO00000002` | 0.98 s / 0.44 s from 90° |
| `0sj000007C7`, `0so00000500` | `GS00` | same values rewritten |
| `0cm` | `GS09` (after 1.3 s) | `gs` during clean → `GS09` (1.2 s delay) |
| `0st` (during clean) | **`GS00` after 1.9 s** | ✅ **`st` replies by itself** (manual ✔); then `gs` → `GS00` |
| `0mrFFFDD000` (−360°) | `POFFFDD74C` | full-turn relative move, 0.94 s |
- After Clean → Stop (6 s) the counter read −355.32°: the same place we found the mount on 11-16
  (−355.31°), so that odd position came from the capture's Clean → Stop.
- Replies to `cm`/`gs` during cleaning come ~1.2 s late (the module is busy); reply timeout 2 s is OK.

### Cross-check: capture vs. ELLO driver source (2026-11-16) — no contradictions
| Item | ELLO_DLL source | Capture | Result |
|---|---|---|---|
| Terminator | `NewLine = "\a"`, `WriteLine` → every TX ends `0x07` | `… 07` on every TX | ✔ |
| Reply framing | reads until `\n`, trims CR/LF/space | replies end CR LF, sometimes split | ✔ |
| Home direction | `Clockwise = '0'`, `AntiClockwise = '1'`; UI default Anticlockwise; held only in the UI | `0ho1`, no traffic on change | ✔ |
| Deg ↔ pulses | type 14 = OpticsRotator: factor = pulses/360 = 398.222; `Math.Round(…, AwayFromZero)` | 31.025°→`3043`, 0.1°→`28`, 3.214°→`500`, 5.0°→`7C7` | ✔ all four |
| Signed data | `ToInt(true)` on 8 hex = signed 32-bit | `FFFFFFFB` = −5 | ✔ |
| Move/home reply | waits for `PO` (or `GS` on error); `PO` length must be 11 | `PO` at end of motion | ✔ |
| Set offset/jog | `so`/`sj` then wait for `GS` | `GS00` | ✔ |
| Clean | `cm`, then wait `GS`; on `GS09` sleep 10 s and send `gs` again (≤ 60 rounds) | `GS09` | ✔ |
| Stop | `st` (no reply awaited), shorten the clean wait to 2 s, `gs` | `st`, `gs`, then 2nd `gs` 3 s later | ✔ explains the 2nd `gs`; whether `st` itself replies is still open |
| Connect | scans addresses `0`–`F` with `in`; 2-motor devices → `i1`, `i2` | same | ✔ |

ELLO timeouts (for reference): read 2 s, move 4 s, home 6 s, status 1 s, clean 10 s per poll.
On an error status ELLO waits 500 ms and resends the command (`GS09` busy is not an error).
Status codes (`DeviceStatus.cs`): 0 OK, 1 communication error, 2 mechanical timeout, 3 command
error, 4 value out of range, 5 module isolated, 6 out of isolation, 7 initialization error,
8 thermal error, 9 busy, 10 sensor error, 11 motor error, 12 out of range, 13 over current,
14 general error.

`i1`/`i2` decoded (`MotorInfo.cs`: loop, motor, current/1866 A, ramp up, ramp down,
fwd period, rev period; freq = 14740 / period kHz):
| Motor | Loop | Motor | Current | Ramp up/down | Fwd freq | Rev freq |
|---|---|---|---|---|---|---|
| 1 (`0I1100005FFFFFFFF00B60093`) | on | off | 0005 | FFFF/FFFF | 81.0 kHz | 100.3 kHz |
| 2 (`0I2100005FFFFFFFF00BC0095`) | on | off | 0005 | FFFF/FFFF | 78.4 kHz | 98.9 kHz |
(Baseline for after a future "Clean and Optimize", which re-tunes these frequencies.)

### Cross-check: capture vs. ELLx manual Issue 12 (2026-11-16)
**Agrees with the capture** ✔
- 9600 baud, 8N1, no parity, **no handshake** (§2.3). Replies end CR LF (§3).
- `in` reply layout (p.10): type `0E`, SN, year, FW `18` (= 1.8), HW `01` (MSB 0 = metric, release 1),
  travel `0168` = 360°, pulses `00023000`. Manual table (p.8): **ELL14 = 143360 pulses/rev,
  398 pulse/deg, 2 motors** ✔.
- `ho` (p.28): byte 3 = direction, **`0` = clockwise, `1` = CCW** → our `0ho1` = anticlockwise ✔.
- `ho`/`ma`/`mr`/`fw`/`bw` reply: `GS` while not completed (e.g. busy/error), **`PO` when the move is
  complete** ✔. Positions/offsets/jog are **signed 32-bit two's complement**, 8 hex digits ✔.
- `go`/`so`, `gj`/`sj` formats ✔ (`HO`, `GJ`, 8 hex). `gp` → `PO` ✔.
- `cm` (p.48): full-range back-and-forth for **a few minutes**; replies `GS09` while running,
  `GS00` when done; any other message during cleaning → `GS09` ✔ (we saw `GS09`).
- Status codes 0–13 identical to ELLO's list ✔. `i1`/`i2` layout and
  period = 14 740 000 / frequency(Hz) ✔ (motor 1: 81.0 / 100.3 kHz).

**Differences / new information** ⚠
1. **Terminator.** The manual defines **no terminator** after commands; each module discards a
   packet if > 2 s pass between bytes, and **CR clears the receive state machine** (aborts a
   half-received command). `0x07` (ELLO) is **not mentioned**. Both forms work on our unit.
2. **`st` reply.** Manual: `st` **replies `GS`** — `GS00` when the stop is complete (p.49), or
   "`GS09` and/or `GS00`" when stopping a continuous jog (p.40). In our capture `st` + `gs` gave only
   **one** `GS00` — so either `st` or `gs` was not answered. Driver: after `st`, read `GS` until
   `GS00` (works either way). Still to check with our own driver.
3. **`st` scope.** Manual: `st` stops **clean/optimize** and **continuous jog** (jog step 0). It is
   not documented as stopping a normal `ma`/`mr`/`ho` move (those finish in ~1 s anyway).
4. **Continuous jog is an overheating risk.** Jog step `0` ⇒ `fw`/`bw` rotate continuously until `st`;
   the manual says velocity **must be 50–70 % (`sv`)** in that mode, "otherwise the unit could
   overheat". ELLO's panel allows jog step 0 without warning. ⇒ our GUI should not allow jog step 0,
   or must set `sv` first (decide in Phase 1/2).
5. **Velocity `gv`/`sv`** (p.42) exists but is not on the ELLO panel; current value unknown
   (read-only `0gv` → `GVxx`, hex %, `64` = 100 %). Not used by us so far.
6. **Home offset** (p.32) is **factory-set** so the stage homes consistently; note it before
   changing; for rotation stages it must be **> 0.7°**. Our factory value: **`0x500` = 3.214°**
   (recorded 2026-11-16). ⇒ "Set Home Offset" in our GUI should be guarded.
7. **Persistence.** `f1/b1/s1` changes must be saved with `us`; the manual does not say whether
   `so`/`sj` are stored without `us` → unknown (ELLO never sends `us` for them).
8. `gs`: "Once read the error value is cleared" — read status once and keep it.
9. `om` (optimize) takes **several minutes** and occupies the bus; rewrites motor frequencies.
10. Status code **14**: ELLO calls it "General error", manual says 14–255 reserved (harmless).
11. ELLO's connect-time scan of addresses `1`–`F` is ELLO's own choice, not a protocol requirement.

---

## SRS DG645 (not installed yet) — digital delay generator

Source: `ref/DG645m.pdf`, chapter *Remote Programming* (printed pp. 41–70 = PDF pp. 55–84;
printed page = PDF page − 14), plus *Operation* pp. 17, 27, 36–38. Everything here is 📖
(manual only) until the unit is installed. **Our need (user, 2026-11-17): adjust the delay of
one channel. No other operations.**

### Interfaces 📖 (pp. 41–44)
| Interface | Settings | Notes |
|---|---|---|
| RS-232 (rear, DB-9 female, DCE) | **9600 baud default** (4800–115200), **8N1, RTS/CTS** fixed | baud set on front panel SHIFT‑RS232 or `IFCF 1,<baud>`; changes apply after interface reset / power cycle |
| LAN 10/100 | **raw socket TCP 5025**, telnet 5024, VXI‑11 | DHCP → Auto‑IP (169.254.x.x) → static, in that priority. **No security** (put behind a firewall). Current IP: SHIFT, STATUS, MODIFY ▲, STATUS ×3 |
| GPIB | address 15 | not used |

All interfaces are enabled by default. Front-panel LEDs: REM (remote lock-out), ACT (traffic),
ERR (a remote command failed; error list under SHIFT‑STATUS → "Error Status").

### Command syntax 📖 (pp. 44–45)
- ASCII, **4-character mnemonics**, case-insensitive (`*XXX` = IEEE-488.2, `XXXX` = DG645).
  Query form = mnemonic + `?`. Parameters separated by commas; **send no spaces/brackets** (the
  manual's own examples do put one space after the mnemonic, e.g. `DLAY 2,0,10e-6` — ⏳ verify).
- Terminator: `;`, CR or LF. Replies end with **CR LF** (default; `XTRM` changes it).
- **Set commands return nothing.** Errors are only visible via `*ESR?` (bit 4 EXE, bit 5 CME) and
  the error queue `LERR?` (pops one code; `0` = empty; 20 entries max, `254` = overflow).
- Input buffer 255 bytes, ≤ 3 parameters of ≤ 25 bytes each.
- Parameters: `i` integer, `f` frequency Hz, `t` time **seconds** (float, e.g. `10e-6`),
  `v` volts.

### Channel numbering 📖 (p. 56, Table 31)
Delay channel `c`/`d`: **0 T0, 1 T1, 2 A, 3 B, 4 C, 5 D, 6 E, 7 F, 8 G, 9 H**.
Output BNC `b`: 0 T0, 1 AB, 2 CD, 3 EF, 4 GH. Output AB: rises at delay A, falls at delay B
(likewise CD, EF, GH). T0 ≡ 0; T1 = end of T0 (not settable). Delay range 0 – 2000 s,
**resolution 5 ps** (pp. 17, 27). Factory default: A = 0, B = A + 10 ns, C = 0, D = C + 10 ns, …

### The command we need 📖 (p. 56)
`DLAY(?)c{,d,t}` — set (query) delay of channel `c` to `t` seconds **relative to channel `d`**.
```
DLAY 2,0,10e-6      set A = T0 + 10 µs
DLAY 3,2,1e-3       set B = A + 1 ms
DLAY?3              → "2,+0.001000000000"   (reference channel, signed seconds, 12 decimals)
```
- The reference is part of every set: setting `DLAY c,d,t` also sets the link of `c` to `d`
  (`LINK(?)c{,d}`: c ≠ T0, neither may be T1; circular links refused, error 13).
- Linked channels move together: if B = A + 1 ms and A changes, the B edge moves too
  (pulse width AB stays constant). Changing a link does not change the absolute time (p. 28).
- Errors: 12 Illegal Delay (out of range), 13 Illegal Link, 10 Illegal Value, 15 Not Allowed
  (another interface holds the lock).
- INSR bit 5 ABORT_DELAY: "a delay cycle was aborted prematurely in order to change instrument
  delay settings" → a change may cut one pulse cycle short (harmless for us? ⏳ ask).

### Full command set 📖 (pp. 46–59) — for reference; only ★ are planned
| Group | Commands |
|---|---|
| IEEE-488.2 | ★`*IDN?` id string (`Stanford Research Systems,DG645,s/n004025,ver1.00.00E`), ★`*CLS` clear ESR/INSR/error queue, ★`*ESR?` event status (clears on read; bits 0 OPC, 2 QYE, 3 DDE, 4 EXE, 5 CME, 7 PON), `*ESE(?)`, ★`*OPC?` returns `1` when all prior commands done, `*PSC(?)`, `*RCL i` recall settings 0–9 (0 = factory), `*RST` = factory defaults (**never send**), `*SAV i` save to 1–9, `*SRE(?)`, `*STB?` (bit 1 BUSY delay cycle running, 2 BURST, 4 MAV), `*TRG` single shot, `*TST?` self test, `*CAL?` auto-cal, `*WAI` |
| Status/display | `DISP(?){i,c}` front-panel display (e.g. `DISP 11,2` = show delay A), `INSE(?)`, `INSR?` (0 TRIG, 1 RATE, 2 END_OF_DELAY, 3 END_OF_BURST, 4 INHIBIT, 5 ABORT_DELAY, 6 PLL_UNLOCK, 7 RB_UNLOCK), ★`LERR?`, `SHDP(?)` display on/off, `TIMB?` timebase 0 int/1 OCXO/2 Rb/3 ext |
| Trigger | `TSRC(?)` source 0 int, 1/2 ext rise/fall, 3/4 single-shot ext, 5 single shot, 6 line; `TRAT(?)` int rate; `TLVL(?)` level; `HOLD(?)` holdoff; `INHB(?)`; `ADVT(?)`; `PRES(?)`, `PHAS(?)` prescalers; step commands `SPHD SPPH SPPS SPTL SPTR`, step sizes `SSHD SSPH SSPS SSTL SSTR` |
| Burst | `BURM(?)` on/off, `BURC(?)` count, `BURD(?)` delay, `BURP(?)` period, `BURT(?)` T0 config; `SPBC SPBD SPBP`, `SSBC SSBD SSBP` |
| Delay/output | ★`DLAY(?)c{,d,t}`, `LINK(?)c{,d}`, `LAMP(?)b{,v}` amplitude, `LOFF(?)b{,v}` offset, `LPOL(?)b{,i}` polarity, `SPDL c,i` step delay up/down by step size, `SSDL(?)c{,t}` delay step size, `SPLA SPLO SSLA SSLO` |
| Interface | `EMAC?`, `EPHY(?)`, `IFCF(?)i{,j}` (0 RS-232 on, 1 baud, 4 TCP/IP, 5 DHCP, 6 Auto-IP, 7 static, 8 raw socket, 9 telnet, 10 VXI-11, 11 IP, 12 mask, 13 gateway), `IFRS i` reset interface, `LCAL` go local, `REMT` go remote (front panel locked), `LOCK?`/`UNLK?` exclusive lock, `XTRM i{,j,k}` reply terminator |

Error codes (pp. 62–67): 0 none · 10–17 execution (10 illegal value, 11 illegal mode,
12 illegal delay, 13 illegal link, 14 recall failed, 15 not allowed/locked, 16 self test,
17 auto cal) · 30/32 query · 40–91 self-test/cal hardware · 110–126 parsing (110 illegal
command, 111 undefined, 112 illegal query, 113 illegal set, 114 null parameter, 115 extra
parameters, 116 missing parameters, 117 overflow, 118 bad float, 120/121 bad integer,
122 bad hex, 126 syntax) · 170/171 communication/overrun · 254 too many errors.

### ⚠ Settings changed remotely are NOT saved automatically 📖 (p. 17)
The DG645 saves front-panel changes to non-volatile memory after ~5 s, but **not changes made
over the remote interface** (to protect the memory). After a power cycle it recalls the last
saved settings → **a delay set by our program is lost at power-off** unless we `*SAV`
explicitly (and even then, which slot is recalled at power-on is unclear: the manual's `*SAV`
description says "1.TODO"). ⏳ decide with the user; verify on hardware.

### Things to verify on the real unit ⏳
1. `*IDN?` reply, CR LF reply terminator, RTS/CTS needed with our USB-RS232 adapter (null-modem
   or straight cable? DG645 is DCE → straight cable to a PC).
2. `DLAY?c` reply format and number of decimals; how a non-multiple of 5 ps is rounded.
3. Space after the mnemonic accepted (manual examples use it; syntax section says no spaces).
4. Front panel stays usable while we talk over RS-232 (no `REMT`), and the display updates.
5. Behaviour of `*SAV` / power-on recall (only if the user wants the delay kept over power-off).

---

## Thorlabs MFF101/M (×2) — flip mount

Source: `ref/Kinesis_apt_communications_protocol.pdf` = Thorlabs *Motion Controllers
Host-Controller Communications Protocol*, **Issue 48, DOC-103274, 10 Aug 2026** (494 pp.;
page numbers below = PDF page). Plus the Kinesis C header
`C:\Program Files\Thorlabs\Kinesis\ThorLabs.MotionControl.FilterFlipper.h`. 📖 unless marked.

### Our unit on this PC ✅ (2026-11-17, Windows device list, read-only)
- **One** flip mount connected: USB `VID_0403&PID_FAF0`, USB serial **`37011815`**
  (prefix 37 = "Motorized filter flipper MFF10x", p. 35), Windows name "APT USB Device".
  **No COM port**: it uses the FTDI **D2XX** driver (`ftd2xx.dll` present in System32 and in the
  Kinesis folder). ⏳ The second MFF101 is not connected yet.
- User controlled it successfully with Kinesis (2026-11-17).
- First probe attempt: `FT_OpenEx("37011815")` → **FT_STATUS 3 (DEVICE_NOT_OPENED)**;
  D2XX listed it as opened by another process (after using Kinesis). Re-plugging USB fixed it.
  → Our driver must report this clearly ("in use by another program — close Kinesis or
  re-plug").

### Read-only probe ✅ (2026-11-17, after the user re-plugged USB; `tools/probe_mff_readonly.py`)
(The earlier "already opened" state is gone after re-plugging — Kinesis had kept it open.)
```
TX 05 00 00 00 50 01                                   HW_REQ_INFO
RX 06 00 54 00 81 50 + 84 bytes: serial 37011815, model "MFF002" (not "MFF101"!), type 16,
   firmware 1.0.3, notes "APT Filter Flipper", hw version 2, mod state 0, channels 1
TX 29 04 01 00 50 01                                   REQ_STATUSBITS
RX 2a 04 06 00 81 50 01 00 02 00 00 90                 chan 1, bits 0x90000002
```
→ identify check: model starts with `MFF`. Bits 28 and 31 are always set (undocumented; ignore).

### Flip test ✅ (2026-11-17 user-approved; unit not on the optical bench, no laser)
Status polled every 20 ms (`REQ_STATUSBITS`); full log in the session scratchpad, summary:
```
REQ_MFF_OPERPARAMS → transit 500 ms, ADC 508, DigIO1 = (1 input-toggle, 1 button, 200 ms),
                     DigIO2 = (3 output-at-position, 0x10 level, 200 ms)  [DIG IO not wired]
start            0x90000002                          ← at "insert"
JOG dir 1   +0.016 s 0x90000012  (moving + still on limit 2)
            +0.094 s 0x90000010  (moving, between)
            +0.41 s  0x90000011  → +0.44 s 0x90000001   ← at position 1 = "retract"
JOG dir 1 again: no motion, bits unchanged (already there)
JOG dir 2   +0.016 s 0x90000011 → 0x90000010 → +0.39 s 0x90000002   ← back at "insert"
JOG dir 2 again: no motion, bits unchanged
end              0x90000002 (original state restored)
```
Findings:
1. **Position = limit bits: 0x01 → position 1, 0x02 → position 2**; neither → between/unknown.
2. **Jog dir 1 → position 1, dir 2 → position 2** (a jog is a "go to position", not a toggle;
   repeating it is harmless).
3. Moving bit is **0x10 in both directions** (0x20 never seen). Briefly both a limit bit and
   0x10 at start/end → "at position" must mean limit bit set **and** 0x10 clear.
4. Flip takes **≈0.4–0.45 s** (transit time 500 ms).
5. **No MOVE_COMPLETED (0x0464)** or any other unsolicited message was received → poll.
6. Unit 37011815: **position 2 = "insert" (current state), position 1 = "retract"** (user).

### Unit 2 ✅ (2026-11-18, user-connected, **6 m USB cable**)
- Windows device list: second "APT USB Device", USB serial **`37006391`**.
- Probe: HW_GET_INFO serial 37006391, model "MFF002", type 16, firmware 1.0.3, "APT Filter
  Flipper", hw 2, mod state 0, channels 1 — same as unit 1. (Bytes 66–77 differ between units:
  unit 2 has "141201Dec…" there — undocumented, ignore.) Status `2a 04 06 00 81 50 01 00 02 00 00
  90` = at **position 2**.
- **Roles (user):** unit 1 (37011815) = **355 nm blocker**, unit 2 (37006391) = **820 nm
  blocker**. Unit 2 insert position = same as unit 1 → **position 2 = insert** (blocking),
  position 1 = retract. Unit 2 not on the optical path yet → free to test (user).
- **Link stability test, read-only** (`tools/mff_link_test.py`, 12:42, our GUI running but not
  using this unit): 2000 status queries back to back → 2000 OK, 0 timeouts, 0 wrong, 0 stray
  bytes; latency median 16.0 ms, max 19.4 ms (≈ FTDI 16 ms latency timer, not the cable).
  500 info queries (90 B) → all byte-identical, 22 ms. 50 open→info→close cycles → 50/50 OK,
  open ≈ 120 ms. Log: `captures/mff2_link_test_2026-11-18_burst.txt`.
- **Soak test, read-only** (12:43–13:13, one status query every 0.2 s): **8665/8665 OK**, 0
  timeouts/wrong/stray, latency median 7.4 ms, max 15.4 ms. → **The 6 m cable link is stable.**
- **Flip test** (13:13, 20 flips with status polled back to back): link still perfect during
  motion (**2804/2804 status replies OK**, max 17 ms). **But 10 of 20 flips to position 1 did
  not stay there.** Trace (scratchpad `flip_trace.py`, every change of the status word):
  ```
  start 0x90000002                    at position 2
  JOG 1  +0.016 0x90000012  +0.080 0x90000010  +0.383 0x90000011   ← reaches position 1 …
         +0.479 0x90000010  +0.767 0x90000012  +0.799 0x90000002   ← … and goes BACK to 2
  JOG 2  no change (already at 2)
  (identical on a second try)
  ```
  Unit 1 never did this (it stays at position 1, see the flip test above).
- **MFF_OPERPARAMS of unit 2** (read-only, 13:16):
  `12 05 22 00 81 50 01 00 f4 01 00 00 fc 01 00 00 01 00 01 00 c8 00 00 00 02 00 02 00 c8 00 00 00
  48 4a 00 00 ee 0e ab ff` → transit 500 ms, ADC 508, DigIO1 = (1 input-toggle, 1 button,
  200 ms) as unit 1, **DigIO2 = (2 input-goto, 2 logic edge, 200 ms)**. Unit 1's DigIO2 =
  (3 output-at-position, 0x10 level).
  **Data length is 34 bytes (len 0x22), not 26 + 6: the last 8 bytes are padding whose content
  changes from read to read** (`48 4a 00 00 ee 0e ab ff`, then `00 00 ec 0e ab ff ab ff`, …) →
  compare only the first 26 bytes.
- Nothing is plugged into unit 2's DIG IO connectors (user, 2026-11-18).
- **DigIO2 test ✅** (13:22–13:23, user-approved; `captures/mff2_digio_test_2026-11-18.txt`):
  `MOT_SET_MFF_OPERPARAMS` (0x0510, RAM only, **no EEPROM save**) with DigIO2 = (3
  output-at-position, 0x10 level, 200 ms), rest unchanged:
  `10 05 20 00 d0 01 01 00 f4 01 00 00 fc 01 00 00 01 00 01 00 c8 00 00 00 03 00 10 00 c8 00 00 00
  00 00 00 00 00 00` (sent with len 32 by mistake; accepted, read-back shows the new values).
  Then **20/20 flips ended at the target**, e.g. `JOG 1: +0.016 12 | +0.080 10 | +0.384 11 |
  +0.416 01`, `JOG 2: … +0.400 02`. → **Cause confirmed: DigIO2 "input-goto" with nothing wired
  sends the mount back to position 2.**
  Restored afterwards (original 34 bytes sent, len 0x22); read-back of the first 26 bytes =
  original. **So unit 2 is back in its faulty original setting** (also after a power cycle,
  since nothing was saved) until a permanent fix is chosen. Ended at position 2 (insert).
  Our driver reports a bounced flip as a failure ("did not reach … Is it blocked?"), never as
  success.
- **After the user changed DIG IO 2 in Kinesis (≈13:28) ✅ checked 13:3x:** unit still reads
  DigIO2 = (2 input-goto, 2 logic edge) and **still bounces** (same trace). Reason: Kinesis
  stored the change **on the PC, not in the device**:
  `C:\ProgramData\Thorlabs\MotionControl\ThorlabsSettingsOverrides.xml` →
  `<DeviceSettingsList SerialNumber="37006391"><DeviceSettingsDefinition Name="FilterFlipper">
  <Settings><Dig_IO_2_OperMode>1</Dig_IO_2_OperMode><Dig_IO_2_SignalMode>1</Dig_IO_2_SignalMode>`.
  Kinesis applies these overrides when *it* connects; other programs (ours) see the device's own
  setting. (The same Kinesis config lists three PDXC2 piezo stages on this PC — serials
  112503750 "355", 112525449 "122", 112516029 "Diagnostics !!! NO LARGER THAN 3mm !!!" — not
  in our scope.)
  → To store it in the device: Kinesis Settings with "Persist settings to the device" (EEPROM),
  or our driver sets it at connect (RAM). ⏳ decide.
- **Fixed in the device ✅ (13:3x):** user set DIG IO 2 in Kinesis (Settings → Current, "Persist
  Settings to the Device" ticked) to output-at-position / level like unit 1, closed Kinesis,
  re-plugged USB. Read-back: `… 03 00 10 00 c8 00 00 00 …` = DigIO2 (3 output-at-position,
  0x10 level, 200 ms) → **stored in the device**. Flip test 13:34
  (`captures/mff2_flips_after_fix_2026-11-18.txt`): **20/20 flips arrived, 0.399–0.400 s**,
  521/521 status replies during flips OK, 500 status + 125 info + 10 reopen all OK. Open time
  now ≈ 510 ms (was ≈ 120 ms before the re-plug; harmless, not understood). Ended at position 2.
  (Kinesis shows a Pin 2 choice "Input: Toggle position / Button input" too — not used: an
  unwired input can be triggered by noise; an output cannot.)

### USB set-up (p. 33) 📖
Thorlabs software does, per device: `FT_SetBaudRate 115200` → `FT_SetDataCharacteristics 8N1`
→ sleep 50 ms → `FT_Purge(RX|TX)` → sleep 50 ms → `FT_ResetDevice` → `FT_SetFlowControl
RTS_CTS` → `FT_SetRts`. Device is opened by its USB serial number.

### Message format (pp. 36–38) 📖
- Binary, little-endian. **6-byte header**: `id(2) p1 p2 dest src` (header only), or
  `id(2) len(2) dest|0x80 src` followed by `len` data bytes.
- Host → device: `dest = 0x50` (generic USB unit), `src = 0x01` (host). Replies have them
  swapped (`dest 0x01`, `src 0x50`; with data: `0x81 0x50`).
- Channel ident = 1 for the MFF.

### Messages applicable to MFF101/MFF102 (p. 18 — the complete list) 📖
| ID | Name | Bytes (TX) | Use for us |
|---|---|---|---|
| 0x0005 / 0x0006 | HW_REQ_INFO / HW_GET_INFO (p. 59) | `05 00 00 00 50 01` → 90-byte reply: serial u32, model char[8], type u16, firmware byte[4] (minor, interim, major), …, HW version u16 @84, mod state u16 @86, channels u16 @88 | identify (check model starts `MFF`, serial matches) |
| 0x046A | MOT_MOVE_JOG (p. 97) | `6A 04 01 dir 50 01`, dir **1 = forward, 2 = reverse** | **flip** (dir ↔ position 1/2 ⏳ verify) |
| 0x0429 / 0x042A | MOT_REQ/GET_STATUSBITS (p. 148) | `29 04 01 00 50 01` → `2A 04 06 00 81 50` + chan u16 + bits u32 | **position + moving** |
| 0x0223 | MOD_IDENTIFY (p. 51) | `23 02 00 00 50 01` | flash the LED (to find which unit is which) |
| 0x0011 / 0x0012 | HW_START/STOP_UPDATEMSGS (p. 57) | `11 00 00 00 50 01` / `12 00 00 00 50 01` | not used: unsolicited status every 100 ms; we poll instead |
| 0x0510/11/12 | MOT_SET/REQ/GET_MFF_OPERPARAMS (p. 204) | REQ `11 05 01 00 50 01` → 40-byte reply | read transit time (read-only) |
| 0x04B9 | MOT_SET_EEPROMPARAMS (p. 113) | saves params to the device | **never** (no settings changes) |

Status bits (p. 135, as for all motors): 0x01 forward (CW) hard limit, 0x02 reverse (CCW) hard
limit, 0x10/0x20 moving fwd/rev, 0x40/0x80 jogging fwd/rev, 0x100 motor connected, 0x200 homing,
0x400 homed, 0x1000 interlock. ⏳ For the MFF, position 1/2 is expected on the two limit bits
(0x01/0x02); Kinesis reports `FF_PositionError = 0` when neither — verify on hardware.

MFF_OPERPARAMS (p. 204): chan u16, transit time ms i32 (**300–2800 ms**), transit time ADC i32
(= 10⁷ × t^−1.591), DigIO1/2: oper mode u16 (1 input-toggle, 2 input-goto, 3 output-at-position,
4 output-in-motion), signal mode u16 (1 button, 2 logic edge, 4 swap, 0x10 level output, 0x20
pulse output, 0x40 inverted), pulse width i32 (10–200 ms), 6 unused bytes (✅ our units: 8
padding bytes, len 0x22 = 34; content changes between reads). Manual example (SET
500 ms): `10 05 22 00 D0 01 01 00 F4 01 00 00 FC 01 00 00 01 00 01 00 C8 00 00 00 01 00 01 00
C8 00 00 00 00 00 00 00 00 00 00 00`. The back-panel DIG IO connectors can flip the mount on
their own — ⏳ ask whether anything is wired to them.

Move end: after a jog the controller sends **MOT_MOVE_COMPLETED 0x0464** (p. 97) unsolicited.
⏳ Verify on hardware whether the MFF sends it; we rely on polling status bits anyway (as Kinesis
does: `FF_GetPosition` = last polled position).

Kinesis C API (header) for comparison: `FF_MoveToPosition(serial, 1|2)`, `FF_GetPosition`
(0 = error, 1, 2), `FF_Get/SetTransitTime` (300–2800 ms), `FF_Home`, `FF_Get/SetIOSettings`.

### Access route — decision proposal
D2XX through `ctypes` (`ftd2xx.dll`, already installed with Kinesis): no driver changes, works
with the serial number directly. Alternatives rejected: enabling the FTDI VCP (changes the
Windows driver setting that Kinesis relies on), Kinesis .NET via `pythonnet` (heavy, opaque, no
raw bytes for the log). A `D2xxTransport` only needs `_open/_close/_write/_read_some/
_discard_input` (same Transport ABC).

### Still to verify ⏳
1. ~~Info, status bits, jog ↔ position, timing, MOVE_COMPLETED~~ ✅ done above (unit 37011815).
2. ~~Second unit: serial, position ↔ name~~ ✅ 37006391, 820 nm blocker, position 2 = insert.
3. Behaviour when a flip is blocked mechanically (expect: no limit bit → timeout → error).

---

## DAQ devices (F8): PicoScopes + IDS camera

Accessed through vendor SDKs (no byte protocol of our own): PicoSDK via `picosdk` ctypes wrappers,
IDS peak via `ids_peak`. Probe tool: `tools/daq_probe.py` (read-only; camera: one short stream).

### SDK installation ✅ (2026-11-18)
- PicoSDK (64-bit) installed by the user: `C:\Program Files\Pico Technology\SDK\lib` (on the
  machine PATH), `ps2000.dll` 3.0.152.6217, `ps3000a.dll` 2.2.160.7569. PicoScope 7 has its own
  older copies; not used. Shells started before the install need the PATH re-read.
- IDS peak runtime (installed) + PyPI `ids-peak` 1.17.0 / `ids-peak-ipl` 1.18.0.

### PicoScopes ✅ (2026-11-18, open → unit info → close, nothing configured)
| Model | Serial | USB | Cal. date | Old-config role |
|---|---|---|---|---|
| 3405D (ps3000a) | JY926/0005 | 3.0 | 24Jul23 | continuous: ch B "212", ch C "820" (DET10A2), Ext trigger |
| 2204A (ps2000) | 12017/0359 | 2.0 | 29Apr25 | continuous: ch A "NO_cell", ch B "Trig" |
| 2204A (ps2000) | 12017/0366 | 2.0 | 29Apr25 | snapshot: H2 VUV PD, ch A "Sig", ch B "Trig" |
- `ps3000aOpenUnit` returned 0 directly (no power-source status 282/286 on this PC). Open takes
  ~3.0 s (3405D) and ~3.7 s per 2204A.
- `ps2000_open_unit` opens the *next free* unit (no serial argument): to get one unit by serial,
  open all, keep the match, close the rest (as the old code does). Not usable while another
  program holds the others → open each 2204A once and keep it.

### IDS camera ✅ (2026-11-18)
- U3-327xCP-C, serial **4110039161**, firmware 3.80.26143, 2048×1536, PixelFormat BayerRG8
  (converted to RGB8), default exposure 15.0 ms, frame rate 20 fps, TriggerMode Off.
- **`DeviceLinkSpeed` = 60 000 000 B/s = USB 2.0 link** (USB 3 would be 400 MB/s). One frame is
  3.1 MB on the link → at most ~19 fps in theory (the old camera notes measured ~10.6 fps
  delivered on the old PC, with frame-ID gaps); at the default 20 fps the first buffer was
  *incomplete* ("Buffer is not large enough"). At 5 fps: 5/5 frames complete, consecutive IDs,
  200 ms apart. → 25 Hz recording (old camera F10) is impossible on this link; needs a USB 3
  port/cable (open question).
- Pitfall (our probe bug): `ipl.ConvertTo(...).get_numpy_3D()` is a *view*; if the converted
  image is not kept, reading the array crashes the process (access violation). Keep the image
  and `.copy()` (the old camera code does this).
- 4 open cycles today (one ended in that crash while streaming); the camera kept working.
