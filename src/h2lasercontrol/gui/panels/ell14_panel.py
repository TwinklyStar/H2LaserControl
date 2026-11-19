"""ELL14 tab: angle display, go-to-angle, step/rotate-by, home; maintenance section collapsed."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...drivers.ell14 import MIN_HOME_OFFSET_DEG
from ..style import C, set_role
from .base import DevicePanel

BUSY_TEXT = {
    "home": "Homing",
    "move_abs": "Rotating",
    "move_rel": "Rotating",
    "move_to": "Rotating",
    "jog_forward": "Stepping",
    "jog_backward": "Stepping",
    "clean": "Cleaning (a few minutes; STOP cancels)",
    "clean_and_optimize": "Cleaning and optimizing (several minutes; STOP cancels)",
    "set_jog_step": "Saving step",
    "set_home_offset": "Saving home offset",
    "go_to_max_energy": "Going to max energy",
    "go_to_min_energy": "Going to min energy",
    "set_energy": "Setting energy",
    "save_max_energy": "Saving max-energy angle",
}


def spin(lo: float, hi: float, value: float, step: float = 1.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(2)
    s.setSingleStep(step)
    s.setSuffix(" °")
    s.setValue(value)
    s.setMinimumWidth(110)
    return s


class Ell14Panel(DevicePanel):
    def build_body(self) -> None:
        self.controls: list[QWidget] = []

        # angle display
        top = QVBoxLayout()
        self.angle_label = QLabel("—")
        set_role(self.angle_label, "big")
        self.angle_label.setStyleSheet("font-size: 28pt;")
        self.info_label = QLabel()
        set_role(self.info_label, "muted")
        top.addWidget(self.angle_label)
        top.addWidget(self.info_label)
        self.body.addLayout(top)

        # 355 nm energy: half-wave plate + PBS (design F4a)
        ebox = QGroupBox("Laser energy (355 nm)")
        e = QGridLayout(ebox)
        e.setHorizontalSpacing(10)
        e.setVerticalSpacing(10)
        self.energy_label = QLabel("—")
        self.energy_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        self.max_label = QLabel()
        self.max_label.setWordWrap(True)
        set_role(self.max_label, "muted")
        e.addWidget(self.energy_label, 0, 0, 1, 4)
        e.addWidget(self.max_label, 1, 0, 1, 4)
        self.energy_controls: list[QWidget] = []
        go_max = self._button("Go to max energy", lambda: self.run("go_to_max_energy"), primary=True)
        go_min = self._button("Go to min energy", lambda: self.run("go_to_min_energy"))
        e.addWidget(go_max, 2, 0, 1, 2)
        e.addWidget(go_min, 2, 2)
        e.addWidget(QLabel("Set energy"), 3, 0)
        self.pct_spin = QDoubleSpinBox()
        self.pct_spin.setRange(0, 100)
        self.pct_spin.setDecimals(1)
        self.pct_spin.setSingleStep(5)
        self.pct_spin.setSuffix(" %")
        self.pct_spin.setValue(100)
        self.pct_spin.setMinimumWidth(110)
        self.controls.append(self.pct_spin)
        e.addWidget(self.pct_spin, 3, 1)
        set_pct = self._button("Set", lambda: self.run("set_energy", percent=self.pct_spin.value()))
        e.addWidget(set_pct, 3, 2)
        self.energy_controls += [go_max, go_min, set_pct, self.pct_spin]
        e.addWidget(self._button("Save current angle as max energy …", self._save_max), 4, 0, 1, 3)
        note = QLabel("Energy % is estimated from the angle: cos²(2·(angle − max angle)); "
                      "min = max + 45°.")
        set_role(note, "muted")
        e.addWidget(note, 5, 0, 1, 4)
        e.setColumnStretch(3, 1)
        self.body.addWidget(ebox)

        # everyday controls
        box = QGroupBox("Rotate")
        g = QGridLayout(box)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        row = 0

        g.addWidget(QLabel("Go to angle"), row, 0)
        self.abs_spin = spin(0, 359.99, 0.0)
        go = self._button("Go", lambda: self.run("move_abs", deg=self.abs_spin.value()), primary=True)
        g.addWidget(self.abs_spin, row, 1)
        g.addWidget(go, row, 2)
        row += 1

        positions = self.cfg.settings.get("positions", {})
        if positions:
            g.addWidget(QLabel("Saved angles"), row, 0)
            named = QHBoxLayout()
            for name, deg in positions.items():
                named.addWidget(self._button(f"{name}  ({float(deg):.2f}°)",
                                             lambda _=False, n=name: self.run("move_to", name=n)))
            named.addStretch(1)
            g.addLayout(named, row, 1, 1, 3)
            row += 1

        g.addWidget(QLabel("Rotate by"), row, 0)
        self.rel_spin = spin(0.01, 360, 1.0, 0.1)
        g.addWidget(self.rel_spin, row, 1)
        rel = QHBoxLayout()
        rel.addWidget(self._button("−  Back", lambda: self.run("move_rel", deg=-self.rel_spin.value())))
        rel.addWidget(self._button("Forward  +", lambda: self.run("move_rel", deg=self.rel_spin.value())))
        g.addLayout(rel, row, 2, 1, 2)
        row += 1

        g.addWidget(QLabel("One step"), row, 0)
        self.step_label = QLabel("—")
        g.addWidget(self.step_label, row, 1)
        jog = QHBoxLayout()
        jog.addWidget(self._button("◀  Step back", lambda: self.run("jog_backward")))
        jog.addWidget(self._button("Step forward  ▶", lambda: self.run("jog_forward")))
        g.addLayout(jog, row, 2, 1, 2)
        row += 1

        g.addWidget(QLabel("Home"), row, 0)
        self.dir_combo = QComboBox()
        self.dir_combo.addItem("Anticlockwise", "ccw")
        self.dir_combo.addItem("Clockwise", "cw")
        self.controls.append(self.dir_combo)
        g.addWidget(self.dir_combo, row, 1)
        g.addWidget(self._button("Home", lambda: self.run("home", direction=self.dir_combo.currentData())),
                    row, 2)
        g.setColumnStretch(4, 1)
        self.body.addWidget(box)

        # maintenance (collapsed)
        self.maint_toggle = QToolButton()
        self.maint_toggle.setText("Maintenance")
        self.maint_toggle.setCheckable(True)
        self.maint_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.maint_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.maint_toggle.setStyleSheet("QToolButton { border: none; background: transparent; font-weight: bold; }")
        self.maint_toggle.toggled.connect(self._toggle_maintenance)
        self.body.addWidget(self.maint_toggle)

        self.maint = QGroupBox()
        m = QGridLayout(self.maint)
        m.addWidget(QLabel("Step size"), 0, 0)
        self.jog_spin = spin(0.01, 360, 5.0)
        m.addWidget(self.jog_spin, 0, 1)
        m.addWidget(self._button("Set", lambda: self.run("set_jog_step", deg=self.jog_spin.value())), 0, 2)
        m.addWidget(QLabel("Home offset"), 1, 0)
        self.offset_spin = spin(MIN_HOME_OFFSET_DEG + 0.01, 359.99, 3.21)
        m.addWidget(self.offset_spin, 1, 1)
        m.addWidget(self._button("Set", self._set_offset), 1, 2)
        offset_note = QLabel("Factory value 3.21°. Change only if you know why.")
        set_role(offset_note, "muted")
        m.addWidget(offset_note, 1, 3)
        clean = QHBoxLayout()
        clean.addWidget(self._button("Clean mechanics", self._clean))
        clean.addWidget(self._button("Clean and optimize motors", self._optimize))
        clean.addStretch(1)
        m.addLayout(clean, 2, 0, 1, 4)
        m.setColumnStretch(3, 1)
        self.maint.hide()
        self.body.addWidget(self.maint)

    def _button(self, text: str, slot, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        if primary:
            set_role(b, "primary")
        b.clicked.connect(slot)
        self.controls.append(b)
        return b

    def _toggle_maintenance(self, on: bool) -> None:
        self.maint.setVisible(on)
        self.maint_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def _save_max(self) -> None:
        pos = self.state.get("position")
        if pos is None:
            return
        old = (self.state.get("max_energy") or {}).get("max_energy_deg")
        prev = f"\n\nPrevious max-energy angle: {old:.2f}°" if old is not None else ""
        if self.confirm("Save max energy",
                        f"Save the current angle {pos % 360:.2f}° as the max-energy angle?{prev}"):
            self.run("save_max_energy")

    def _set_offset(self) -> None:
        v = self.offset_spin.value()
        if self.confirm("Home offset", f"Change the home offset to {v:.2f}°?\n\n"
                        "It was set at the factory (3.21°) so that homing is repeatable."):
            self.run("set_home_offset", deg=v)

    def _clean(self) -> None:
        if self.confirm("Clean mechanics", "The mount rotates back and forth over its full range "
                        "for a few minutes. Continue?"):
            self.run("clean")

    def _optimize(self) -> None:
        if self.confirm("Clean and optimize", "The mount rotates for several minutes and the motor "
                        "frequencies are re-tuned (this changes device settings). Continue?"):
            self.run("clean_and_optimize")

    def busy_text(self, action: str) -> str:
        return BUSY_TEXT.get(action, super().busy_text(action).rstrip(" …")) + " …"

    def on_progress(self, info: dict) -> None:
        if "elapsed" in info and self.busy:
            text = self.busy_label.text().split("  (")[0]
            self.busy_label.setText(f"{text}  ({info['elapsed']:.0f} s)")

    def on_action_done(self, action: str, result: Any) -> None:
        if action == "connect":  # start the editors from the device's current values
            self._init_editors = True

    def update_view(self) -> None:
        pos = self.state.get("position")
        if pos is None or not self.connected:
            self.angle_label.setText("—")
            self.angle_label.setStyleSheet(f"font-size: 28pt; color:{C.GREY}")
            self.info_label.setText("")
            self.step_label.setText("—")
        else:
            shown = pos % 360
            self.angle_label.setText(f"{shown:.2f}°")
            self.angle_label.setStyleSheet("font-size: 28pt;")
            self.angle_label.setToolTip(f"Device counter: {pos:.3f}° (shown modulo 360°)")
            jog = self.state.get("jog_step")
            off = self.state.get("home_offset")
            self.info_label.setText(f"Home offset {off:.2f}°")
            self.step_label.setText(f"{jog:.2f}°")
            if getattr(self, "_init_editors", False):
                self._init_editors = False
                self.abs_spin.setValue(round(shown, 2) % 360)
                self.jog_spin.setValue(jog)
                self.offset_spin.setValue(off)
        saved = self.state.get("max_energy") if self.connected else None
        frac = self.state.get("energy_fraction")
        if not self.connected:
            self.energy_label.setText("—")
            self.max_label.setText("")
        elif saved:
            self.energy_label.setText(f"Now ≈ {100 * frac:.0f} % of max" if frac is not None else "—")
            by = f" by {saved['saved_by']}" if saved.get("saved_by") else ""
            when = str(saved.get("saved_at", ""))[:16].replace("T", " ")
            self.max_label.setText(f"Max-energy angle {saved['max_energy_deg']:.2f}° "
                                   f"(saved {when}{by})")
        else:
            self.energy_label.setText("Max-energy angle not saved yet")
            self.max_label.setText("Tune the angle for maximum energy, then press "
                                   "“Save current angle as max energy”.")
        for w in self.controls:
            w.setEnabled(self.can_act)
        for w in self.energy_controls:
            w.setEnabled(self.can_act and bool(saved))
            w.setToolTip("" if saved else "Save the max-energy angle first")
