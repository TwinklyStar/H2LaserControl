"""Main application window — live view, acquisition controls, capture and multi-shot recording."""
from __future__ import annotations

import enum
import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..analysis.autogain import (
    Apply,
    AutoGainLimits,
    AutoGainTuner,
    Done,
    Fail,
    roi_area,
)
from ..camera.base import CameraBase
from ..camera.controller import AcquisitionController
from ..config import AppConfig, load_config, save_config
from ..storage.recorder import (
    FrameRecorder,
    RecordStats,
    make_run_dir,
    make_single_path,
)
from .live_view import LiveView

_log = logging.getLogger("laserdaq.gui")

# H2LaserControl merge: camera configs live in <program>/config/camera (was <repo>/configs).
# Relative output_dir values are resolved against the program folder (default data/camera).
_PROGRAM_DIR = Path(__file__).resolve().parents[4]
_CONFIGS_DIR = _PROGRAM_DIR / "config" / "camera"
_GAIN_SCALE = 100  # slider integer ↔ float: value / _GAIN_SCALE


class AppState(enum.Enum):
    LIVE = "live"
    RUNNING = "running"
    AUTOGAIN = "autogain"


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        camera: CameraBase | None = None,
        camera_label: str = "",
        parent: QWidget | None = None,
        configs_dir: str | Path | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._configs_dir = Path(configs_dir) if configs_dir else _CONFIGS_DIR
        self._base_dir = Path(base_dir) if base_dir else _PROGRAM_DIR
        self._config = config
        self._camera_label = camera_label
        self._app_state = AppState.LIVE
        self._run_total: int = 0
        self._tuner: AutoGainTuner | None = None
        self._camera: CameraBase | None = None
        self._controller: AcquisitionController | None = None
        self._camera_ready = False
        self._hw_exposure_limits: tuple[float, float] = (100.0, 100_000.0)
        self._display_fps: float | None = None
        self._camera_fps: float | None = None

        self._stall_timer = QTimer(self)
        self._stall_timer.setInterval(1000)
        self._stall_timer.timeout.connect(self._check_camera_stall)
        self._stall_shown = False
        self._autogain_watchdog = QTimer(self)
        self._autogain_watchdog.setSingleShot(True)
        self._autogain_watchdog.timeout.connect(self._on_autogain_timeout)
        self._setup_ui()

        if camera is not None:
            self.set_camera(camera)

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self) -> None:
        self.setWindowTitle("LaserDAQ")

        # Central layout: live view (left) + sidebar (right)
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        self._live_view = LiveView(self._config)
        self._live_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root_layout.addWidget(self._live_view, stretch=3)

        sidebar = self._build_sidebar()
        root_layout.addWidget(sidebar)

        self._live_view.set_roi_visible(self._config.gain_roi_enabled)
        self._refresh_config_list()
        self._set_state(AppState.LIVE)  # initialise visibility of state-dependent widgets

        # Permanent left/right status-bar labels — never overwrite each other
        _init_fps = "No camera" + (f"  ·  {self._camera_label}" if self._camera_label else "")
        self._fps_label = QLabel(_init_fps)
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._status_label.clear)
        self.statusBar().addWidget(self._fps_label, 1)
        self.statusBar().addPermanentWidget(self._status_label)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)

        # Config selector group (always visible)
        cfg_grp = QGroupBox("Config")
        cfg_layout = QHBoxLayout(cfg_grp)
        self._config_combo = QComboBox()
        cfg_layout.addWidget(self._config_combo, 1)
        self._config_reload_btn = QPushButton("↺")
        self._config_reload_btn.setMaximumWidth(30)
        cfg_layout.addWidget(self._config_reload_btn)
        self._config_save_btn = QPushButton("Save…")
        cfg_layout.addWidget(self._config_save_btn)
        layout.addWidget(cfg_grp)

        # Acquisition group  (hidden while RUNNING)
        acq = QGroupBox("Acquisition")
        self._acq_group = acq
        acq_form = QFormLayout(acq)

        self._exposure_spin = QDoubleSpinBox()
        self._exposure_spin.setSuffix(" µs")
        self._exposure_spin.setDecimals(1)
        self._exposure_spin.setRange(100.0, 100_000.0)
        self._exposure_spin.setValue(self._config.exposure_us)
        self._exposure_max_check = QCheckBox("Max")
        self._exposure_max_check.setChecked(self._config.exposure_max)
        self._exposure_spin.setEnabled(not self._config.exposure_max)
        exp_widget = QWidget()
        exp_v = QVBoxLayout(exp_widget)
        exp_v.setContentsMargins(0, 0, 0, 0)
        exp_v.setSpacing(2)
        exp_v.addWidget(self._exposure_spin)
        exp_v.addWidget(self._exposure_max_check)
        acq_form.addRow("Exposure:", exp_widget)

        self._analog_gain_slider = QSlider(Qt.Horizontal)
        self._analog_gain_slider.setRange(100, 1250)  # 1.0–12.5 default
        self._analog_gain_slider.setValue(int(self._config.analog_gain * _GAIN_SCALE))
        self._analog_gain_label = QLabel(f"{self._config.analog_gain:.2f}")
        self._analog_gain_label.setMinimumWidth(35)
        ag_row = QHBoxLayout()
        ag_row.setContentsMargins(0, 0, 0, 0)
        ag_row.addWidget(self._analog_gain_slider, 1)
        ag_row.addWidget(self._analog_gain_label)
        acq_form.addRow("Analog Gain:", ag_row)

        self._digital_gain_slider = QSlider(Qt.Horizontal)
        self._digital_gain_slider.setRange(100, 1600)  # 1.0–16.0 default
        self._digital_gain_slider.setValue(int(self._config.digital_gain * _GAIN_SCALE))
        self._digital_gain_label = QLabel(f"{self._config.digital_gain:.2f}")
        self._digital_gain_label.setMinimumWidth(35)
        dg_row = QHBoxLayout()
        dg_row.setContentsMargins(0, 0, 0, 0)
        dg_row.addWidget(self._digital_gain_slider, 1)
        dg_row.addWidget(self._digital_gain_label)
        acq_form.addRow("Digital Gain:", dg_row)

        layout.addWidget(acq)

        # Auto gain group: ROI over the laser spot + one-shot tuning button
        ag_grp = QGroupBox("Auto Gain")
        self._autogain_group = ag_grp
        ag_lay = QHBoxLayout(ag_grp)
        self._gain_roi_check = QCheckBox("ROI")
        self._gain_roi_check.setToolTip("Show the auto-gain ROI box; drag it over the laser spot")
        self._gain_roi_check.setChecked(self._config.gain_roi_enabled)
        ag_lay.addWidget(self._gain_roi_check)
        self._autogain_btn = QPushButton("Auto Gain")
        self._autogain_btn.setEnabled(False)
        ag_lay.addWidget(self._autogain_btn, 1)
        layout.addWidget(ag_grp)

        # Trigger group  (hidden while RUNNING)
        tg = QGroupBox("Trigger")
        self._trigger_group = tg
        tg_layout = QVBoxLayout(tg)

        mode_row = QHBoxLayout()
        self._free_radio = QRadioButton("Free Run")
        self._hw_radio = QRadioButton("Hardware")
        self._free_radio.setChecked(True)
        mode_row.addWidget(self._free_radio)
        mode_row.addWidget(self._hw_radio)
        tg_layout.addLayout(mode_row)

        fps_form = QFormLayout()
        self._cam_fps_spin = QDoubleSpinBox()
        self._cam_fps_spin.setDecimals(1)
        self._cam_fps_spin.setRange(0.5, 30.0)
        self._cam_fps_spin.setValue(5.0)
        self._cam_fps_spin.setSuffix(" fps")
        fps_form.addRow("FPS:", self._cam_fps_spin)
        tg_layout.addLayout(fps_form)

        self._trigger_apply_btn = QPushButton("Apply")
        tg_layout.addWidget(self._trigger_apply_btn)

        layout.addWidget(tg)

        # Capture button (LIVE state)
        self._capture_btn = QPushButton("Capture")
        self._capture_btn.setEnabled(False)
        layout.addWidget(self._capture_btn)

        # Multi-shot run button (LIVE only)
        self._run_btn = QPushButton("Multi-shot run…")
        layout.addWidget(self._run_btn)

        # RUNNING state widgets
        self._run_progress_label = QLabel("")
        self._run_progress_label.setVisible(False)
        layout.addWidget(self._run_progress_label)
        self._stop_run_btn = QPushButton("Stop Run")
        self._stop_run_btn.setVisible(False)
        layout.addWidget(self._stop_run_btn)

        layout.addStretch()

        # Wire signals
        self._config_combo.currentTextChanged.connect(self._on_config_selected)
        self._config_reload_btn.clicked.connect(self._refresh_config_list)
        self._config_save_btn.clicked.connect(self._save_session_config)
        self._capture_btn.clicked.connect(self._do_capture_and_save)
        self._run_btn.clicked.connect(self._do_open_run_dialog)
        self._stop_run_btn.clicked.connect(self._stop_run)
        self._exposure_spin.valueChanged.connect(self._on_exposure_changed)
        self._exposure_max_check.toggled.connect(self._on_exposure_max_toggled)
        self._analog_gain_slider.valueChanged.connect(self._on_analog_gain_changed)
        self._digital_gain_slider.valueChanged.connect(self._on_digital_gain_changed)
        self._free_radio.toggled.connect(self._on_trigger_mode_ui_changed)
        self._trigger_apply_btn.clicked.connect(self._apply_trigger_config)
        self._gain_roi_check.toggled.connect(self._on_gain_roi_toggled)
        self._autogain_btn.clicked.connect(self._on_autogain_clicked)
        self._live_view.roi_changed.connect(lambda *_: self._update_autogain_enabled())

        # Wrap in a scroll area so widget visibility changes never resize the window
        scroll = QScrollArea()
        scroll.setWidget(sidebar)
        scroll.setWidgetResizable(True)
        # H2LaserControl merge: was a fixed 276 px (260 content + ~16 scrollbar). Inside the
        # merged program (Fusion style) the content needs more, so it was cut off on the right:
        # size it to the content's own minimum width instead (never narrower than before).
        self._sidebar_scroll = scroll
        self._fit_sidebar()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _fit_sidebar(self) -> None:
        """H2LaserControl merge: sidebar width = its content's minimum width (>= old 276 px)."""
        scroll = self._sidebar_scroll
        scrollbar = scroll.verticalScrollBar().sizeHint().width()
        content = scroll.widget().minimumSizeHint().width()
        scroll.setFixedWidth(max(276, content + scrollbar + 2 * scroll.frameWidth() + 4))

    def showEvent(self, event) -> None:
        self._fit_sidebar()  # again after the style/fonts are applied
        super().showEvent(event)

    # -------------------------------------------------------------- Camera --

    def set_camera(self, camera: CameraBase) -> None:
        self._camera = camera
        try:
            camera.open()
        except Exception as exc:
            msg = f"Camera error: {exc}"
            _log.error("set_camera: %s", msg)
            self._show_status(msg)
            return
        lo, hi = camera.get_exposure_limits()
        self._hw_exposure_limits = (lo, hi)
        self._check_link_speed(camera)
        alo, ahi = camera.get_analog_gain_limits()
        self._analog_gain_slider.blockSignals(True)
        self._analog_gain_slider.setRange(int(alo * _GAIN_SCALE), int(ahi * _GAIN_SCALE))
        self._analog_gain_slider.blockSignals(False)
        dlo, dhi = camera.get_digital_gain_limits()
        self._digital_gain_slider.blockSignals(True)
        self._digital_gain_slider.setRange(int(dlo * _GAIN_SCALE), int(dhi * _GAIN_SCALE))
        self._digital_gain_slider.blockSignals(False)
        self._update_exposure_limit()
        # Apply the (possibly clamped) config acquisition settings to the camera
        camera.set_exposure(self._exposure_spin.value())
        camera.set_analog_gain(self._analog_gain_slider.value() / _GAIN_SCALE)
        camera.set_digital_gain(self._digital_gain_slider.value() / _GAIN_SCALE)
        self._start_controller()

    _FULL_FRAME_BYTES = 2048 * 1536  # 8-bit raw Bayer frame the camera sends

    def _check_link_speed(self, camera: CameraBase) -> None:
        """Permanent warning in the status bar if the camera link cannot carry 25 fps."""
        speed = camera.link_speed_bytes_per_s()
        if speed is None:
            return
        max_fps = speed / self._FULL_FRAME_BYTES
        if max_fps < 25.0:
            warn = (f"SLOW USB LINK {speed / 1e6:.0f} MB/s (USB 2.0) - max ~{max_fps:.0f} fps; "
                    f"use a USB 3 port/cable")
            _log.warning(warn)
            self._camera_label = (self._camera_label + "  ·  " if self._camera_label else "") + warn
            self._update_fps_status()

    def _start_controller(self) -> None:
        if self._controller is not None:
            self._controller.stop()
            self._controller.setParent(None)
        self._controller = AcquisitionController(self._camera, parent=self, display_fps=30.0)
        self._controller.frame_ready.connect(self._on_frame_ready)
        self._controller.fps_updated.connect(self._on_fps_updated)
        self._controller.camera_fps_updated.connect(self._on_camera_fps_updated)
        self._controller.error_occurred.connect(self._on_camera_error)
        self._controller.recording_progress.connect(self._on_recording_progress)
        self._controller.recording_finished.connect(self._on_recording_finished)
        self._controller.start()
        self._camera_ready = True
        self._stall_timer.start()
        self._capture_btn.setEnabled(True)
        self._update_autogain_enabled()

    def _update_exposure_limit(self) -> None:
        lo, hi = self._hw_exposure_limits
        fps = self._cam_fps_spin.value()
        max_exp = min(hi, 1_000_000.0 / max(fps, 0.1))
        self._exposure_spin.blockSignals(True)
        self._exposure_spin.setRange(lo, max_exp)
        self._exposure_spin.setValue(max(lo, min(max_exp, self._exposure_spin.value())))
        self._exposure_spin.blockSignals(False)
        if self._exposure_max_check.isChecked():
            self._apply_max_exposure()

    _STALL_S = 4.0

    def _check_camera_stall(self) -> None:
        """Tell the operator when the camera stops delivering frames (USB / power trouble)."""
        ctrl = self._controller
        if ctrl is None or ctrl._thread is None or self._hw_radio.isChecked():
            return  # (in hardware-trigger mode no frames are normal until a trigger arrives)
        idle = ctrl.idle_seconds
        # Frames are expected at least every ~2 s even at the slowest FPS setting.
        if idle > max(self._STALL_S, 3.0 / max(self._cam_fps_spin.value(), 0.1)):
            self._status_label.setText(
                f"CAMERA NOT DELIVERING FRAMES for {idle:.0f} s - check USB cable / power"
            )
            self._status_label.setStyleSheet("color: #e07000; font-weight: bold;")
            self._status_timer.stop()
            self._stall_shown = True
        elif self._stall_shown:
            self._stall_shown = False
            self._status_label.clear()
            self._status_label.setStyleSheet("")

    def shutdown(self) -> None:
        """Stop everything that touches the camera.  Idempotent; also wired to aboutToQuit."""
        self._stall_timer.stop()
        self._autogain_watchdog.stop()
        self._tuner = None
        if self._controller is not None:
            self._controller.stop()  # stops acquisition, flushes a recording, closes camera
        elif self._camera is not None:
            # Controller was never started (camera.open() failed) - still close cleanly.
            try:
                self._camera.close()
            except Exception:  # noqa: BLE001
                _log.exception("camera.close failed")

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    @Slot(object)
    def _on_frame_ready(self, frame: np.ndarray) -> None:
        self._live_view.update_frame(frame)
        if self._app_state is AppState.AUTOGAIN:
            self._feed_autogain(frame)
        if self._controller is not None:
            self._controller.notify_frame_displayed()

    @Slot(str)
    def _on_camera_error(self, msg: str) -> None:
        self._show_status(f"Camera error: {msg}")

    # ----------------------------------------------- Trigger configuration --

    def _on_trigger_mode_ui_changed(self, checked: bool) -> None:
        # checked = True when Free Run is selected; False when Hardware selected
        self._cam_fps_spin.setEnabled(checked)

    def _apply_trigger_config(self) -> None:
        if self._camera is None or self._controller is None:
            return
        fps = self._cam_fps_spin.value()
        mode = "free_run" if self._free_radio.isChecked() else "hardware"
        self._display_fps = None
        self._camera_fps = None
        self._controller.pause()
        self._camera.set_fps(fps)
        self._camera.set_trigger_for_streaming(mode)
        self._controller.resume()
        if mode == "free_run":
            self._update_exposure_limit()
        else:
            lo, hi = self._hw_exposure_limits
            self._exposure_spin.blockSignals(True)
            self._exposure_spin.setRange(lo, hi)
            self._exposure_spin.blockSignals(False)
            if self._exposure_max_check.isChecked():
                self._apply_max_exposure()
        self._show_status("Settings applied.")

    def _show_status(self, msg: str) -> None:
        self._status_label.setText(msg)
        self._status_timer.start(8000)

    def _update_fps_status(self) -> None:
        cam = f"{self._camera_fps:.1f}" if self._camera_fps is not None else "—"
        disp = f"{self._display_fps:.1f}" if self._display_fps is not None else "—"
        text = f"Cam: {cam} fps  |  Disp: {disp} fps"
        if self._camera_label:
            text += f"  ·  {self._camera_label}"
        self._fps_label.setText(text)

    @Slot(float)
    def _on_fps_updated(self, fps: float) -> None:
        self._display_fps = fps
        self._update_fps_status()

    @Slot(float)
    def _on_camera_fps_updated(self, fps: float) -> None:
        self._camera_fps = fps
        self._update_fps_status()
        if self._hw_radio.isChecked() and self._app_state is AppState.LIVE:
            # In hardware-trigger mode the longest usable exposure is set by the
            # camera's own frame rate (not the throttled display rate).
            lo, hi = self._hw_exposure_limits
            max_exp = min(hi, 1_000_000.0 / max(fps, 0.1))
            self._exposure_spin.blockSignals(True)
            self._exposure_spin.setRange(lo, max_exp)
            if self._exposure_spin.value() > max_exp:
                self._exposure_spin.setValue(max_exp)
            self._exposure_spin.blockSignals(False)
            if self._exposure_max_check.isChecked():
                self._apply_max_exposure()

    # --------------------------------------------------- Config selector --

    def _refresh_config_list(self) -> None:
        """Re-scan configs/ and repopulate the combo box; preserve current selection."""
        current = self._config_combo.currentText()
        self._config_combo.blockSignals(True)
        self._config_combo.clear()
        if self._configs_dir.is_dir():
            names = sorted(p.name for p in self._configs_dir.glob("*.toml"))
            self._config_combo.addItems(names)
            target = current if current else "default.toml"
            idx = self._config_combo.findText(target)
            if idx < 0:
                idx = self._config_combo.findText("default.toml")
            if idx >= 0:
                self._config_combo.setCurrentIndex(idx)
        self._config_combo.blockSignals(False)

    def _on_config_selected(self, name: str) -> None:
        if name:
            self._load_session_config(self._configs_dir / name)

    def _save_session_config(self) -> None:
        """Save the current in-memory config to a TOML file in configs/."""
        current = self._config_combo.currentText()
        name, ok = QInputDialog.getText(
            self, "Save Config", "Filename (saved to config/camera/):",
            text=current or "default.toml",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if not name.endswith(".toml"):
            name += ".toml"
        dest = self._configs_dir / name
        try:
            save_config(self._config, dest)
        except Exception as exc:
            self._show_status(f"Save failed: {exc}")
            return
        self._refresh_config_list()
        # Select the saved file without triggering a reload
        idx = self._config_combo.findText(name)
        if idx >= 0:
            self._config_combo.blockSignals(True)
            self._config_combo.setCurrentIndex(idx)
            self._config_combo.blockSignals(False)
        self._show_status(f"Saved: config/camera/{name}")

    def _load_session_config(self, path: str | Path) -> None:
        """Load a TOML config and replace the current session config."""
        path = Path(path)
        try:
            new_cfg = load_config(path)
        except Exception as exc:
            self._show_status(f"Config load error: {exc}")
            return
        self._config = new_cfg
        # Update acquisition spinboxes; let _update_exposure_limit clamp to hardware range
        self._exposure_spin.blockSignals(True)
        self._exposure_spin.setValue(self._config.exposure_us)
        self._exposure_spin.blockSignals(False)
        self._exposure_max_check.blockSignals(True)
        self._exposure_max_check.setChecked(self._config.exposure_max)
        self._exposure_max_check.blockSignals(False)
        self._exposure_spin.setEnabled(not self._config.exposure_max)
        self._analog_gain_slider.blockSignals(True)
        self._analog_gain_slider.setValue(int(self._config.analog_gain * _GAIN_SCALE))
        self._analog_gain_label.setText(f"{self._config.analog_gain:.2f}")
        self._analog_gain_slider.blockSignals(False)
        self._digital_gain_slider.blockSignals(True)
        self._digital_gain_slider.setValue(int(self._config.digital_gain * _GAIN_SCALE))
        self._digital_gain_label.setText(f"{self._config.digital_gain:.2f}")
        self._digital_gain_slider.blockSignals(False)
        self._update_exposure_limit()  # calls _apply_max_exposure() if exposure_max is True
        self._live_view.bind_roi(self._config.gain_roi)
        self._gain_roi_check.blockSignals(True)
        self._gain_roi_check.setChecked(self._config.gain_roi_enabled)
        self._gain_roi_check.blockSignals(False)
        self._live_view.set_roi_visible(self._config.gain_roi_enabled)
        self._update_autogain_enabled()
        if self._camera is not None:
            self._set_camera(
                exposure_us=self._exposure_spin.value(),
                analog_gain=self._analog_gain_slider.value() / _GAIN_SCALE,
                digital_gain=self._digital_gain_slider.value() / _GAIN_SCALE,
            )

    # ---------------------------------------------------- Exposure / gain --

    def _set_camera(self, **settings: float) -> None:
        """Send exposure/gain to the camera via the acquisition thread (never from the GUI
        thread: a blocked SDK call there froze the whole window)."""
        if self._controller is not None:
            self._controller.apply_settings(**settings)
        elif self._camera is not None:
            if "exposure_us" in settings:
                self._camera.set_exposure(settings["exposure_us"])
            if "analog_gain" in settings:
                self._camera.set_analog_gain(settings["analog_gain"])
            if "digital_gain" in settings:
                self._camera.set_digital_gain(settings["digital_gain"])

    def _on_exposure_changed(self, value: float) -> None:
        if self._exposure_max_check.isChecked():
            return  # max checkbox owns the camera exposure while pinned
        self._config.exposure_us = value
        if self._camera is not None:
            self._set_camera(exposure_us=value)

    def _on_exposure_max_toggled(self, checked: bool) -> None:
        self._exposure_spin.setEnabled(not checked)
        self._config.exposure_max = checked
        if checked:
            self._apply_max_exposure()

    def _apply_max_exposure(self) -> None:
        max_val = self._exposure_spin.maximum()
        self._exposure_spin.blockSignals(True)
        self._exposure_spin.setValue(max_val)
        self._exposure_spin.blockSignals(False)
        self._config.exposure_us = max_val
        if self._camera is not None:
            self._set_camera(exposure_us=max_val)

    def _on_analog_gain_changed(self, raw: int) -> None:
        gain = raw / _GAIN_SCALE
        self._analog_gain_label.setText(f"{gain:.2f}")
        self._config.analog_gain = gain
        if self._camera is not None:
            self._set_camera(analog_gain=gain)

    def _on_digital_gain_changed(self, raw: int) -> None:
        gain = raw / _GAIN_SCALE
        self._digital_gain_label.setText(f"{gain:.2f}")
        self._config.digital_gain = gain
        if self._camera is not None:
            self._set_camera(digital_gain=gain)

    # ---------------------------------------------------------------- State machine --

    def _set_state(self, state: AppState) -> None:
        self._app_state = state
        in_live = state is AppState.LIVE
        in_running = state is AppState.RUNNING
        in_auto = state is AppState.AUTOGAIN

        self._capture_btn.setEnabled(in_live and self._camera_ready)
        self._run_btn.setVisible(not in_running)
        self._run_btn.setEnabled(in_live)
        self._run_progress_label.setVisible(in_running)
        self._stop_run_btn.setVisible(in_running)
        # Acquisition / Trigger / Auto Gain: hidden while recording; frozen while tuning
        for grp in (self._acq_group, self._trigger_group, self._autogain_group):
            grp.setVisible(not in_running)
        self._acq_group.setEnabled(in_live)
        self._trigger_group.setEnabled(in_live)
        self._gain_roi_check.setEnabled(in_live)
        self._live_view.set_roi_locked(in_auto)
        self._autogain_btn.setText("Stop" if in_auto else "Auto Gain")
        self._update_autogain_enabled()

    # ----------------------------------------------------- Auto gain (F11) --

    def _update_autogain_enabled(self) -> None:
        """Auto Gain is available only with ROI on, a usable ROI, a camera, and in LIVE."""
        if self._app_state is AppState.AUTOGAIN:
            self._autogain_btn.setEnabled(True)  # it is the Stop button
            return
        ok = (
            self._app_state is AppState.LIVE
            and self._camera_ready
            and self._gain_roi_check.isChecked()
            and self._roi_has_area()
        )
        self._autogain_btn.setEnabled(ok)

    def _roi_has_area(self) -> bool:
        roi = self._config.gain_roi
        frame = self._live_view.last_frame
        if frame is None:
            return roi.xmax > roi.xmin and roi.ymax > roi.ymin
        return roi_area(roi, frame.shape[0], frame.shape[1]) > 0

    def _on_gain_roi_toggled(self, checked: bool) -> None:
        self._config.gain_roi_enabled = checked
        self._live_view.set_roi_visible(checked)
        self._update_autogain_enabled()

    def _on_autogain_clicked(self) -> None:
        if self._app_state is AppState.AUTOGAIN:
            self._finish_autogain("Auto gain stopped (current settings kept).")
        else:
            self._start_autogain()

    def _start_autogain(self) -> None:
        if (
            self._app_state is not AppState.LIVE
            or self._camera is None
            or not self._gain_roi_check.isChecked()
        ):
            return
        cfg = self._config
        free_run = self._free_radio.isChecked()
        hw_lo, _ = self._hw_exposure_limits
        floor = cfg.autogain_free_run_min_exposure_us
        exp_min = max(hw_lo, floor) if free_run else hw_lo
        exp_max = self._exposure_spin.maximum()
        if exp_min > exp_max:
            self._show_status(
                f"FPS too high for {floor / 1000:g} ms minimum exposure - "
                f"lower FPS to <= {1_000_000.0 / floor:g}"
            )
            return
        if not self._roi_has_area():
            self._show_status("ROI is empty or outside the image.")
            return

        self._exposure_max_check.setChecked(False)  # the tuner owns the exposure
        alo, ahi = self._camera.get_analog_gain_limits()
        dlo, dhi = self._camera.get_digital_gain_limits()
        step = floor if free_run else None  # whole laser pulses per exposure in free run
        limits = AutoGainLimits(exp_min, exp_max, alo, ahi, dlo, dhi, exp_step_us=step)
        start = (
            self._exposure_spin.value(),
            self._analog_gain_slider.value() / _GAIN_SCALE,
            self._digital_gain_slider.value() / _GAIN_SCALE,
        )
        settle = 2
        self._tuner = AutoGainTuner(
            limits, start, n_avg=cfg.autogain_n_avg, settle=settle, target=cfg.autogain_target
        )
        if self._tuner.settings != start:
            # start values were outside the limits (e.g. below the 40 ms free-run floor)
            self._apply_autogain_settings(*self._tuner.settings)
            self._tuner.skip(settle)
        self._set_state(AppState.AUTOGAIN)
        self._show_status("Auto gain running...")
        self._autogain_watchdog.start(15_000)

    def _feed_autogain(self, frame: np.ndarray) -> None:
        if self._tuner is None:
            return
        self._autogain_watchdog.start(15_000)
        action = self._tuner.feed(frame, self._config.gain_roi)
        if isinstance(action, Apply):
            self._apply_autogain_settings(action.exp_us, action.ag, action.dg)
        elif isinstance(action, Done):
            c = action.channel_peaks
            self._finish_autogain(
                f"Auto gain: peak {action.peak:.0f} (R {c['R']:.0f} / G {c['G']:.0f} / "
                f"B {c['B']:.0f}) · {action.exp_us / 1000:.1f} ms · AG {action.ag:.2f} · "
                f"DG {action.dg:.2f}"
                + (" (minimum settings reached)"
                   if action.peak > self._config.autogain_target * 1.1 else "")
            )
        elif isinstance(action, Fail):
            self._finish_autogain(f"Auto gain failed: {action.reason}")

    def _apply_autogain_settings(self, exp_us: float, ag: float, dg: float) -> None:
        """Push tuner settings to the camera, widgets (signals blocked) and the config."""
        self._exposure_spin.blockSignals(True)
        self._exposure_spin.setValue(exp_us)
        self._exposure_spin.blockSignals(False)
        for slider, label, val in (
            (self._analog_gain_slider, self._analog_gain_label, ag),
            (self._digital_gain_slider, self._digital_gain_label, dg),
        ):
            slider.blockSignals(True)
            slider.setValue(int(round(val * _GAIN_SCALE)))
            slider.blockSignals(False)
            label.setText(f"{slider.value() / _GAIN_SCALE:.2f}")
        self._config.exposure_us = self._exposure_spin.value()
        self._config.analog_gain = self._analog_gain_slider.value() / _GAIN_SCALE
        self._config.digital_gain = self._digital_gain_slider.value() / _GAIN_SCALE
        if self._camera is not None:
            self._set_camera(
                exposure_us=self._config.exposure_us,
                analog_gain=self._config.analog_gain,
                digital_gain=self._config.digital_gain,
            )

    def _finish_autogain(self, message: str) -> None:
        self._autogain_watchdog.stop()
        self._tuner = None
        self._set_state(AppState.LIVE)
        self._show_status(message)

    def _on_autogain_timeout(self) -> None:
        if self._app_state is AppState.AUTOGAIN:
            self._finish_autogain("Auto gain failed: no frames received.")

    # ------------------------------------------------------- Recording (F10) --

    _DISPLAY_FPS_LIVE = 30.0
    _DISPLAY_FPS_RECORDING = 10.0  # live view is secondary while recording

    def _start_recording(self, n: int, single: bool = False) -> bool:
        """Record the next n camera frames as BMPs (every frame, not just displayed ones)."""
        if self._app_state is not AppState.LIVE or self._controller is None:
            return False
        if single:
            rec = FrameRecorder(make_single_path(self._output_dir()),
                                config=self._config, single=True)
        else:
            rec = FrameRecorder(make_run_dir(self._output_dir()), config=self._config)
        try:
            self._controller.start_recording(rec, n)
        except Exception as exc:  # noqa: BLE001
            self._show_status(f"Cannot start recording: {exc}")
            return False
        self._run_total = n
        self._run_progress_label.setText(f"Recorded 0/{n} · dropped 0")
        self._controller.set_display_fps(self._DISPLAY_FPS_RECORDING)
        self._set_state(AppState.RUNNING)
        return True

    def _output_dir(self) -> Path:
        """config.output_dir; a relative path is relative to the program folder."""
        out = Path(self._config.output_dir)
        return out if out.is_absolute() else self._base_dir / out

    def _do_capture_and_save(self) -> None:
        """Record the next single camera frame."""
        if self._controller is None or not self._camera_ready:
            self._show_status("No frame available yet.")
            return
        self._start_recording(1, single=True)

    def _do_open_run_dialog(self) -> None:
        """Open the RunDialog; start recording if the user confirms."""
        from .run_dialog import RunDialog

        dlg = RunDialog(self)
        if dlg.exec() == RunDialog.DialogCode.Accepted:
            self._do_start_run(dlg.n_shots)

    def _do_start_run(self, n: int) -> None:
        """Begin an N-frame recording run."""
        if self._controller is None:
            self._show_status("No camera connected.")
            return
        self._start_recording(n)

    def _stop_run(self) -> None:
        """Finish the recording early; the UI returns to LIVE on recording_finished."""
        if self._controller is not None:
            self._controller.stop_recording()

    @Slot(int, int, int)
    def _on_recording_progress(self, submitted: int, written: int, dropped: int) -> None:
        if self._app_state is AppState.RUNNING:
            text = f"Recorded {written}/{self._run_total} · dropped {dropped}"
            self._run_progress_label.setText(text)

    @Slot(object)
    def _on_recording_finished(self, stats: RecordStats) -> None:
        if self._controller is not None:
            self._controller.set_display_fps(self._DISPLAY_FPS_LIVE)
        self._run_total = 0
        self._set_state(AppState.LIVE)
        msg = f"Recorded {stats.written}/{stats.submitted} frames -> {stats.run_dir}"
        if stats.dropped:
            msg = f"WARNING: {stats.dropped} frame(s) DROPPED (disk too slow). " + msg
            self._status_label.setStyleSheet("color: #e07000; font-weight: bold;")
        else:
            self._status_label.setStyleSheet("")
        self._show_status(msg)
