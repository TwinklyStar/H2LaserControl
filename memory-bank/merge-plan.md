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
| M2 | **PicoScope core.** `daq/picoscope/`: digitizer worker (from `H2LaserDigitizer`), `RootManager`, ADC conversion copied; virtual digitizer for tests. Configs from the old Python files → TOML with the **same keys**. Tests: ROOT branches/types, CSV header/rows and snapshot CSV equal to the old code's output for the same synthetic input. | ✅ 2026-11-18 (sim): `tests/test_picoscope.py` |
| M3 | **Streaming service.** Start / stop / status / error per acquisition, op-log entries, clean shutdown (flush ROOT, close scopes). One scope failing does not silently stop the others (shown in red in its tab). | ✅ 2026-11-18 (sim): `PicoSession` |
| M4 | **PicoScope tabs.** "Scope monitor" (continuous: trends + averaged waveforms, port of `H2MonitorApp`) and "VUV PD snapshot" (port of `H2SnapshotApp`: Freeze / Save, ± range; its display-only Pause removed). Start / Pause / Stop; keep running in the background. | ✅ sim (`tests/test_gui_daq.py`); ⏳ user check on hardware |
| M5 | **Camera tab.** `laserdaq` package moved in (kept as a sub-package), its `MainWindow` embedded as the tab unchanged (sidebar, live view, histogram, auto gain, capture, multi-shot run, config selector). Its tests ported. Its logging / fault log / hang watchdog wired into our app. BMP→ROOT script kept. | ✅ sim (191 ported camera tests pass; real-camera tests only with `H2_CAMERA_HW=1`); ⏳ hardware |
| M6 | **Integration.** Shutdown order, single instance lock, launcher, README §, CLAUDE.md, `architecture.md`. | ✅ 2026-11-18: 292 passed, 21 skipped, ruff clean |
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

6. Pause = no triggers taken, nothing written, display freezes; scope and files stay open;
   Resume continues in the same files. The old snapshot "Pause" (display only) is removed.
7. Camera tab: start page only (camera not opened) until Start; Close camera returns to it.

## Changes vs. the old programs (deliberate)
- Each scope stops alone on an error (old: one crash stopped all).
- A trigger wait interrupted by Stop / Pause is not written (old: wrote one partial waveform).
- 3405D opened by serial; SDK calls behind a per-DLL lock (see architecture.md).
- Trigger rate shown in the tab every 5 s (old: printed every 1000 triggers); "No trigger for
  10 s" shown in the tab (old: printed).
- Data folders: `data/picoscope` (was `data/`), `data/camera` (was `output/`); camera configs
  in `config/camera` (was `configs/`).
- Scope tabs: start page until Start / after Stop, fresh plots on each Start; light colours
  instead of the dark Catppuccin theme (user 2026-11-18).
- Scope config chosen in a drop-down on the start page (user 2026-11-18): the old
  `config/*.py` files are now `config/picoscope/*.toml` (same keys + title + mode; data_path
  `data/...` -> `data/picoscope/...`); invalid files are listed with the reason; the old
  history viewer config was not converted (viewer dropped).
- Camera sidebar width = its content's minimum width (was a fixed 276 px, cut off in the
  merged program's Fusion style; user 2026-11-18). Otherwise the camera window is unchanged.

## Open points
- **Camera on USB 2.0** (`DeviceLinkSpeed` 60 MB/s, M1): 25 Hz full-frame recording impossible;
  USB 3 port/cable needed if 25 Hz is wanted.
- Camera: old docs say `signal_stop()` must not call `KillWait()`, the code does (copied as
  is). Watch for "Apply needs two clicks" / stale aborts in the hardware test.
- Output names in `devices.toml` are the old ones (`FreeSpacePD_2026June`, `NOCell_2026June`,
  `H2PD_2026B`): new names for the merged program's data?
- ~~Two 2204A tabs at once~~: OK for 15 min with the per-DLL lock (M7, 2026-11-18). Whether
  the lock could be dropped is not tested (no need).
- ~~3405D `PICO_TIMEOUT` / `PICO_NOT_RESPONDING`~~: caused by the USB cabling (3405D on the
  same hub as the 2204As; the old code failed the same way). Fixed by moving the 3405D to the
  other hub. Kept as safety net: skip a failed readout, reconnect after 3 in a row (deliberate
  change vs. old code). **Keep the 3405D off the 2204As' hub.**
