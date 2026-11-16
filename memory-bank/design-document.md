# H2LaserControl — Design Document

## 1. Motivation (why this project exists)

In the H2 laser room, several devices from different vendors are each operated through
their **own vendor software**:

| Device | Vendor | Role in the setup | Vendor software |
|---|---|---|---|
| HIT-MV stage controller (2 linear feedthroughs) | Sigma Koki (OptoSigma) | Insert / retract things (e.g. a photodiode) into the beam path | Sigma Koki software (e.g. SGCommander) |
| ELL14 rotation mount | Thorlabs (Elliptec) | Rotate an optic | Elliptec software (ELLO) |
| MFF101/M motorized flip mount | Thorlabs | Flip an optic in/out (e.g. dump a laser beam) | Thorlabs Kinesis |

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
  query position / busy state, stop, home (origin return).
- F3. MFF101: flip to position 1 / 2 (named, e.g. "DUMP" / "PASS"), query current position.
- F4. ELL14: home, move to absolute angle, query angle.
- F5. Operation log: every user action and every device command/response with timestamp,
  stored persistently on disk and viewable.
- F6. (Phase 3) Ordering rules defined in config, checked before every action.
- F7. (Phase 4) User macros: named sequences of actions, runnable with one button.

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
- Non-serial devices (cameras, DAQ, Ethernet/GPIB instruments) — may be added later via the
  same driver interface.
- Remote / multi-PC access.
- Detailed interlock rule design (deferred to Phase 3).
