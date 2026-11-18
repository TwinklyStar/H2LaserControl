# H2LaserControl — Design Document

## 1. Motivation (why this project exists)

In the H2 laser room, several devices from different vendors are each operated through
their **own vendor software**:

| Device | Vendor | Role in the setup | Vendor software |
|---|---|---|---|
| HIT-MV stage controller (2 linear feedthroughs) | Sigma Koki (OptoSigma) | In the VUV diagnostic chamber: axis 0 inserts the **VUV photodiode** (pulse energy), axis 1 inserts the **45° VUV mirror** that sends the 122 nm beam to the VUV beam profiler. Both normally **retracted (30000000 units = 60 mm real)**; inserted = 0 (mechanical origin) | Sigma Koki software |
| ELL14 rotation mount | Thorlabs (Elliptec) | Rotates the **half-wave plate for the 355 nm laser** in front of a **PBS** → sets the transmitted 355 nm **pulse energy** (user, 2026-11-17). Users save the angle that **maximizes the output energy** | Elliptec software (ELLO) |
| MFF101/M motorized flip mount | Thorlabs | Flip an optic in/out (e.g. dump a laser beam) | Thorlabs Kinesis |
| DG645 digital delay generator (not installed yet) | Stanford Research Systems | Timing/delays; controlled via **RS-232** now, maybe **LAN** later | — (manual `ref/DG645m.pdf`, remote programming from printed p. 41) |

Problems with this situation:

1. **Steep learning curve.** Every user has to learn several different programs, each with
   its own UI, conventions and pitfalls. Most users only need a handful of actions
   ("flip mirror in", "insert photodiode", "rotate waveplate to X°").
2. **No coordination between devices (no interlock / ordering).** Because each program is
   independent, nothing prevents an unsafe order of operations. Example: the photodiode
   on a linear feedthrough must **not** be inserted before the flip mount has dumped the
   laser, otherwise the photodiode can be damaged. Today this relies on the operator's memory.
3. **No unified record.** There is no single history of *who did what, when*. When
   something goes wrong it is hard to reconstruct the sequence of operations.

### System context
Setup described in `ref/NIMA_vuv_light_source.pdf` (muonium laser ionization system, J-PARC MLF H2
area): 122 nm (VUV) and 355 nm pulses are transported under vacuum through the laser steering
chamber and the **VUV diagnostic chamber** to the muonium-production target. Either feedthrough
inserted ⇒ the 122 nm beam does **not** reach the target, so "both retracted" is the safe/normal
state during muon operation.

## 2. Goal

Build **one unified, simple Python GUI** that:

- controls all of the above devices from one window,
- shows each device's live state clearly,
- enforces **operation ordering rules** ("interlock" in the soft sense: e.g. *dump laser
  with flip mount → then insert photodiode*),
- records an **operation history log** (timestamp, device, action, raw command, result),
- later allows **user-defined one-button sequences** (macros) of several operations.

Primary users: **lab members who are not the developer** → the GUI must be simple,
self-explanatory and hard to misuse.

## 3. Scope and approach

- Start with **serial-port devices** (all three current devices talk over a (virtual) serial
  port / USB-FTDI link).
- Strategy: **protocol-first, sniff-to-verify.**
  - Use the official protocol manuals where they exist (ELLx protocol manual, Thorlabs APT
    protocol manual, Sigma Koki HIT command reference).
  - Monitor the vendor software's serial traffic for the specific operations we actually
    use, to confirm the exact command strings, port settings and device configuration
    (axis numbers, positions).
  - Reproduce only the **limited command subset** we need, from our own code.
- Built **incrementally**, each phase usable on its own.

### Phases

| Phase | Deliverable | "Done" means |
|---|---|---|
| 0 | Project setup + protocol capture | Repo, environment, device inventory, captured/verified command list per device |
| 1 | **Script control** | Each device fully operated by Python scripts (connect, status, the moves we use), every command logged |
| 2 | **GUI** | One window controlling all devices, live status, operation log visible |
| 3 | **Interlock / ordering** | Configurable rules block or auto-sequence unsafe orders (e.g. flip-dump before PD insert) |
| 4 | **Programmable operations** | User-defined one-button macros composed of several actions |

Operation logging is built in from Phase 1 (not bolted on later), because the driver layer
is where every command passes through.

## 4. Requirements

### Functional
- F1. Connect / disconnect each device; detect and report connection loss.
- F2. HIT-MV: move each of the 2 linear feedthroughs to named positions ("IN" / "OUT"),
  query position / busy state, stop, home (origin return). IN = origin return (as in SGSample),
  with **homing max speed raised to 1000000 units/s (2 mm/s real)** to halve the insert time.
- F2a. **HIT-MV interlock (user, 2026-11-17): the two feedthroughs must never be inserted at the
  same time.** Always retract one before inserting the other. "Inserted" here means *not fully
  retracted* (inserted, partly inserted after a stop, or moving). GUI: while one axis is not
  retracted, the other axis's operation buttons are disabled (with the reason). Also enforced in
  the driver (scripts can't bypass it); unknown position ⇒ blocked.
- F2b. **No confirmation dialog when inserting the VUV photodiode or mirror** (user,
  2026-11-18): the Insert button starts the move at once (the interlock F2a still applies).
- F2c. **Positions lost after a controller restart ⇒ nothing moves** (user, 2026-11-18): a
  power cycle resets both counters to 0 whatever the real position. Both reading 0 (impossible
  under F2a) ⇒ GUI shows "POSITION UNKNOWN", Insert and Retract locked, also in the driver.
  Recovery by the user: check by eye, home + retract with HIT Sample.
- F3. MFF101: flip to position 1 / 2 (named, e.g. "DUMP" / "PASS"), query current position.
- F3b. DG645: **only adjust the delay of one channel** (user, 2026-11-17): show it, set a new
  value, step it up/down; no other DG645 operations. Transport must allow RS-232 now and LAN
  (TCP) later without changing the driver.
- F4. ELL14: all functions of the ELLO panel — home (with direction), get/set home offset,
  get/set jog step, jog forward/backward, move absolute, move relative, query angle,
  clean device, clean & optimize, stop.
- F4a. **355 nm energy control (user, 2026-11-17, option 2):** "Save current angle as max energy",
  "Go to max energy", "Go to min energy" (= max + 45°) and "Set energy %" using
  T = cos²(2·(θ − θ_max)). Home offset stays factory-set (Home = fixed reference); the max-energy
  angle is stored by the program (`config/saved_angles.json`), every change logged (old → new).
- F5. Operation log: every user action and every device command/response with timestamp,
  stored persistently on disk and viewable.
- F6. (Phase 3) Ordering rules defined in config, checked before every action.
- F7. (Phase 4) User macros: named sequences of actions, runnable with one button.
- F8. **Merge with the DAQ program (user, 2026-11-17): ideally ONE program.** The DAQ PC
  runs PicoScope waveform acquisition and camera operation; these become part of this program
  (e.g. their own tabs), not a separate program beside it. The merged program runs on the DAQ
  PC. Details (language/toolkit of the DAQ program, structure) still to be studied → merge plan.
  Decisions (user, 2026-11-18), plan in `memory-bank/merge-plan.md`:
  - F8a. PicoScope: **one tab for continuous DAQ** and **one tab for the H2 VUV PD snapshot**.
    Once started they **keep running** (also while another tab is shown) until explicitly stopped.
    Each tab has its own **Start / Pause / Stop** buttons; nothing starts by itself when the
    program starts. Configs: continuous = old `config_monitor_2026A`, snapshot = old
    `config_H2PD_261103`. History viewer dropped for now.
  - F8d. Data location: **`data/picoscope`** and **`data/camera`** (in the program folder);
    the file formats and names inside stay as before.
  - F8b. Camera: its own tab, an **exact copy of the current camera GUI**. No terminal menu (TUI).
  - F8c. **Output formats stay exactly the same** (PicoScope ROOT `rawWave` + CSV + snapshot CSV;
    camera BMP / frames.csv / config TOML / BMP→ROOT).
  - The merged program runs on this PC (scopes and camera are connected here).
  - F8e. Waveform display (user, 2026-11-18): **no trigger waveform** in the monitor or the
    snapshot (the trigger channel = each scope's `trigger_channel`; files unchanged); the
    **trigger rate** of each scope is shown in the status bar instead.
  - F8f. Monitor trend **time window selectable**: last 10 min, 30 min, 1 hr, 3 hr, 5 hr, 12 hr,
    1 day, 3 days, 7 days, 14 days (old: fixed 4000 points ≈ 5 h); the history is read
    automatically from the old daily CSV files.
  - F8g. Snapshot works **like an oscilloscope** (user, 2026-11-18): refresh ~10 fps, ideally
    25 fps; the plot is the average of the **latest N** waveforms, N set with up/down arrows:
    1, 2, 4 … 1024 (and ∞ = all since Clear, our reading of "or infinite"). **Statistics box**:
    offset (mean of the first 5 % of the points), integrated area with the offset subtracted,
    std, N, stderr. **Clear** button empties the average and the statistics and restarts.

### GUI structure (user, 2026-11-17)
- **One tab per device**, like browser (Chrome) tabs; the user switches between tabs. Devices are
  **not** put together on one screen.
- Adding a device later = adding a tab (a new device *type* needs one new panel class; another
  device of a known type needs only a config entry).
- Keep it **clean and easy to use**.
- **Two levels (user, 2026-11-19):** top tabs **Control** (motor feedthroughs, rotation mount,
  flip mounts, later DG645) and **DAQ** (scope monitor, snapshot, camera); the device tabs are
  sub-tabs inside them.

### Non-functional
- N1. Runs on the single lab PC (Windows 11) in the `H2LaserControl` conda environment.
- N2. Simple UI for non-expert users; named positions instead of raw numbers.
- N3. Device COM ports identified robustly (by USB serial number, not by COM number,
  which can change).
- N4. A misbehaving device must not freeze the GUI (I/O off the UI thread, timeouts).
- N5. Vendor software and our program cannot use the same port simultaneously — our
  program replaces the vendor software for daily operation.

## 5. Safety note

There is currently **no hardware interlock**. The software ordering rules (Phase 3) reduce
operator error but are not a substitute for a hardware interlock; if a mistake could cause
injury (not only equipment damage), a hardware interlock should be considered separately.

## 6. Out of scope (for now)
- Other Ethernet/GPIB instruments — may be added later via the same driver interface.
  (PicoScope + camera are now in scope via F8.)
- Remote / multi-PC access.
- Detailed interlock rule design (deferred to Phase 3).
