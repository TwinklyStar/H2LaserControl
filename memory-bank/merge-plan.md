# Merge plan: PicoScope DAQ + IDS camera into H2LaserControl (F8)

Requirements: `design-document.md` F8, F8a–F8c. Old code (reference only, git-ignored):
`DAQ_oldcode/H2LaserDAQ` (PicoScope) and `DAQ_oldcode/IDS-Camera` (package `laserdaq`).
Survey of the old code: `progress.md`, 2026-11-18.

## Principles
- **Port, don't redesign.** Acquisition maths, file writers and the camera GUI are copied with
  the minimum changes needed (PyQt5 → PySide6, imports, paths). Output files must be identical.
- The scopes and the camera are **streaming** devices (25 Hz data), unlike the existing
  command/reply devices. Data goes straight to files and plots; only user actions (start, stop,
  settings, config choice, captures, errors) go to the operation log.
- Each acquisition runs off the GUI thread; a tab switch never stops it (F8a).
- Measurement devices are passive: running them does not move anything on the beamline.
  Camera: avoid unnecessary open/close cycles (the old notes report the link dying after a few).

## Steps

| Step | What | Done when |
|---|---|---|
| M0 | **Environment.** DAQ packages in `pyproject.toml` and the `H2LaserControl` env. PicoSDK DLLs findable. | ✅ 2026-11-18 (picosdk 1.1, ids-peak 1.17, uproot 5.7.7, pyqtgraph 0.14, numpy 2.5.5, opencv 5.1; PicoSDK installed by the user). |
| M1 | **Read-only hardware check.** Open each scope by serial, read unit info, close; IDS camera: open, 3 frames, close, read link speed (USB 2 vs 3). Record in `docs/protocols.md`. | ✅ 2026-11-18: 3 scopes match the configs; camera OK but on a **USB 2.0** link |
| M2 | **PicoScope core.** `daq/picoscope/`: digitizer worker (from `H2LaserDigitizer`), `RootManager`, ADC conversion copied; virtual digitizer for tests. Configs from the old Python files → TOML with the **same keys**. Tests: ROOT branches/types, CSV header/rows and snapshot CSV equal to the old code's output for the same synthetic input. | tests pass, outputs byte-compatible |
| M3 | **Streaming service.** Start / stop / status / error per acquisition, op-log entries, clean shutdown (flush ROOT, close scopes). One scope failing does not silently stop the others (shown in red in its tab). | sim tests |
| M4 | **PicoScope tabs.** "Scope monitor" (continuous: trends + averaged waveforms, port of `H2MonitorApp`) and "VUV PD snapshot" (port of `H2SnapshotApp`: Pause / Freeze / Save, ± range). Start/Stop buttons; keep running in the background. | sim GUI tests; user check on hardware |
| M5 | **Camera tab.** `laserdaq` package moved in (kept as a sub-package), its `MainWindow` embedded as the tab unchanged (sidebar, live view, histogram, auto gain, capture, multi-shot run, config selector). Its tests ported. Its logging / fault log / hang watchdog wired into our app. BMP→ROOT script kept. | camera tests pass; user check on hardware |
| M6 | **Integration.** Shutdown order, single instance lock, launcher, README §, CLAUDE.md, `architecture.md`. | full suite + ruff clean |
| M7 | **Acceptance with the user** on hardware: long continuous run, snapshot save, camera capture / run; compare files with old-program files. | user OK |

## Decided (user, 2026-11-18)
1. PicoSDK (64-bit) installed → `C:\Program Files\Pico Technology\SDK\lib` on PATH. ✅
2. Configs: continuous = `config_monitor_2026A.py` (3405D JY926/0005 "212"/"820" + 2204A
   12017/0359 "NO_cell"/"Trig"); snapshot = `config_H2PD_261103.py` (2204A 12017/0366, output
   `H2PD_2026B`). Each scope belongs to one tab.
3. Each PicoScope tab: **Start / Pause / Stop**, independent; nothing starts at program start.
   On program close: stop (files closed cleanly).
4. Data: `data/picoscope/` (old `data/` content: `root/`, `csv/`, `snapshots/`) and
   `data/camera/` (old `output/` content: `YYYY-MM-DD/…`). Names/formats inside unchanged.
5. History viewer: dropped for now.

## Open points
- **Pause meaning** (proposal): Pause = no new triggers are taken and nothing is written, the
  scope stays open and the files stay open; Resume continues in the same ROOT/CSV file.
  Stop = close files and release the scope. The old snapshot window's own "Pause" button
  (freezes only the display while data keeps coming) would clash in name.
- **Camera tab start:** the old camera GUI opens the camera at launch. Same Start / Stop rule
  as the scope tabs (camera not opened until Start)?
- **Camera on USB 2.0** (`DeviceLinkSpeed` 60 MB/s, M1): 25 Hz full-frame recording impossible;
  USB 3 port/cable needed if 25 Hz is wanted.
- Camera: old docs say `signal_stop()` must not call `KillWait()`, the code does. Check on M5.
