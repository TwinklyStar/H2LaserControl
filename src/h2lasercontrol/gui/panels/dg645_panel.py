"""Delay generator tab (SRS DG645): adjust our laser-trigger edge (C) in µs around nominal, within
hard limits; every channel shown read-only; Maintenance (collapsed) changes the nominal value
(user 2026-11-20, design-document F3b-F3h)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from ...drivers.dg645 import WATCHED, delay_text, ms_text, us_text
from ..style import C, set_role
from .base import DevicePanel

BUSY_TEXT = {"set_offset": "Setting the trigger delay", "step": "Stepping the trigger delay",
             "set_nominal": "Saving the nominal value",
             "use_current_as_nominal": "Saving the nominal value",
             "unlock": "Unlocking the front panel", "read_now": "Reading"}
EPS_US = 1e-6  # 1 ps, for comparisons with the limits


def _when(iso: str | None) -> str:
    return str(iso or "")[:16].replace("T", " ")


class Dg645Panel(DevicePanel):
    def build_body(self) -> None:
        s = self.cfg.settings
        self.ch = str(s.get("channel", "C")).upper()
        self.width_ch = str(s.get("width_channel", "D")).upper()
        self.step_us = float(s.get("step_us", 0.1))
        self.min_us = float(s.get("min_offset_us", -1.5))
        self.max_us = float(s.get("max_offset_us", 3.0))
        self.nominal_s = float(s["nominal_s"])
        self.controls: list[QWidget] = []
        self.stop_btn.hide()  # a delay change is instant: nothing to stop

        # our edge: offset from nominal, big
        top = QVBoxLayout()
        title = QLabel(f"Laser trigger delay (channel {self.ch}, rising edge of output "
                       f"{self.ch}{self.width_ch})")
        title.setStyleSheet("font-weight: bold;")
        self.offset_label = QLabel("—")
        set_role(self.offset_label, "big")
        self.offset_label.setStyleSheet("font-size: 28pt;")
        self.abs_label = QLabel()
        set_role(self.abs_label, "muted")
        self.warn_label = QLabel()
        self.warn_label.setWordWrap(True)
        self.warn_label.hide()
        top.addWidget(title)
        top.addWidget(self.offset_label)
        top.addWidget(self.abs_label)
        top.addWidget(self.warn_label)
        self.body.addLayout(top)

        # front panel (user 2026-11-20, F3i′): only an Unlock button, for the rare case
        lockbox = QGroupBox("DG645 front panel")
        lk = QHBoxLayout(lockbox)
        lk.setSpacing(10)
        self.lock_note = QLabel("If the DG645 front panel is locked (REM light on, keys do "
                                "not work), click Unlock, or press the key “3” on the DG645.")
        self.lock_note.setWordWrap(True)
        set_role(self.lock_note, "muted")
        self.unlock_btn = QPushButton("Unlock")
        self.unlock_btn.setToolTip("Send LCAL: the DG645 front-panel keys work again "
                                   "(changes no settings)")
        self.unlock_btn.clicked.connect(lambda: self.run("unlock"))
        self.read_btn = QPushButton("Read now")
        self.read_btn.setToolTip("Read all channels now (the keys do not respond for ~0.5 s)")
        self.read_btn.clicked.connect(lambda: self.run("read_now"))
        lk.addWidget(self.lock_note, 1)
        lk.addWidget(self.read_btn)
        lk.addWidget(self.unlock_btn)
        self.body.addWidget(lockbox)

        # adjust
        box = QGroupBox(f"Adjust {self.ch}")
        g = QGridLayout(box)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        g.addWidget(QLabel("Step"), 0, 0)
        steps = QHBoxLayout()
        self.minus_btn = self._button(f"−  {self.step_us:g} µs", lambda: self._step(-1))
        self.plus_btn = self._button(f"+  {self.step_us:g} µs", lambda: self._step(+1))
        steps.addWidget(self.minus_btn)
        steps.addWidget(self.plus_btn)
        steps.addStretch(1)
        g.addLayout(steps, 0, 1, 1, 3)

        g.addWidget(QLabel("Set to"), 1, 0)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(self.min_us, self.max_us)
        self.spin.setDecimals(3)
        self.spin.setSingleStep(self.step_us)
        self.spin.setSuffix(" µs")
        self.spin.setMinimumWidth(130)
        self.spin.setToolTip("Offset from nominal")
        self.controls.append(self.spin)
        g.addWidget(self.spin, 1, 1)
        self.set_btn = self._button("Set", lambda: self.run("set_offset",
                                                            offset_us=self.spin.value()))
        g.addWidget(self.set_btn, 1, 2)
        self.nominal_btn = self._button("Back to nominal", lambda: self.run("set_offset",
                                                                            offset_us=0.0))
        g.addWidget(self.nominal_btn, 1, 3)

        self.limits_label = QLabel()  # text set in update_view (the nominal value can change)
        self.limits_label.setWordWrap(True)
        set_role(self.limits_label, "muted")
        g.addWidget(self.limits_label, 2, 0, 1, 5)
        self.last_label = QLabel()
        self.last_label.setWordWrap(True)
        g.addWidget(self.last_label, 3, 0, 1, 5)
        g.setColumnStretch(4, 1)
        self.body.addWidget(box)

        # all channels, read only
        allbox = QGroupBox("All channels (read only: the other channels belong to other groups)")
        a = QGridLayout(allbox)
        a.setHorizontalSpacing(24)
        for col, head in enumerate(("Channel", "Set as", "Time after T0")):
            h = QLabel(head)
            set_role(h, "muted")
            a.addWidget(h, 0, col)
        self.rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for i, ch in enumerate(WATCHED, 1):
            ours = ch in (self.ch, self.width_ch)
            name = QLabel(f"{ch}  (laser)" if ours else ch)  # user 2026-11-20: not "ours"
            rel, absolute = QLabel("—"), QLabel("—")
            for col, w in enumerate((name, rel, absolute)):
                if ours:
                    w.setStyleSheet("font-weight: bold;")
                a.addWidget(w, i, col)
            self.rows[ch] = (name, rel, absolute)
        a.setColumnStretch(3, 1)
        self.body.addWidget(allbox)
        self.read_note = QLabel()
        self.read_note.setWordWrap(True)
        set_role(self.read_note, "muted")
        seconds = self.cfg.settings.get("read_interval_s")
        every = (f"every {float(seconds) / 60:g} min" if seconds and float(seconds) >= 60
                 else f"every {float(seconds):g} s" if seconds else "every few seconds")
        self._read_note_text = (f"The DG645 is read {every} and with “Read now” (its keys do not "
                                f"respond during a reading, about 0.5 s). Changes made on the "
                                f"front panel are written to the operation history at the next "
                                f"reading.")
        self.body.addWidget(self.read_note)
        self._build_maintenance()

    def _build_maintenance(self) -> None:
        """Collapsed, like the rotation mount's (user 2026-11-20): change the nominal value."""
        self.maint_toggle = QToolButton()
        self.maint_toggle.setText("Maintenance")
        self.maint_toggle.setCheckable(True)
        self.maint_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.maint_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.maint_toggle.setStyleSheet(
            "QToolButton { border: none; background: transparent; font-weight: bold; }")
        self.maint_toggle.toggled.connect(self._toggle_maintenance)
        self.body.addWidget(self.maint_toggle)

        self.maint = QGroupBox()
        m = QGridLayout(self.maint)
        m.setHorizontalSpacing(10)
        m.setVerticalSpacing(10)
        self.maint_controls: list[QWidget] = []
        m.addWidget(QLabel(f"Nominal value of {self.ch}"), 0, 0)
        self.nominal_label = QLabel("—")
        self.nominal_label.setStyleSheet("font-weight: bold;")
        m.addWidget(self.nominal_label, 0, 1, 1, 3)
        self.use_current_btn = QPushButton(f"Use current {self.ch} as nominal …")
        self.use_current_btn.clicked.connect(self._use_current)
        m.addWidget(self.use_current_btn, 1, 0, 1, 2)
        m.addWidget(QLabel("Set nominal to   T0 +"), 2, 0)
        self.nominal_spin = QDoubleSpinBox()
        self.nominal_spin.setRange(0.000001, 999.999999)
        self.nominal_spin.setDecimals(6)  # 1 ns
        self.nominal_spin.setSingleStep(0.0001)  # 0.1 µs
        self.nominal_spin.setSuffix(" ms")
        self.nominal_spin.setMinimumWidth(150)
        m.addWidget(self.nominal_spin, 2, 1)
        set_nominal = QPushButton("Set …")
        set_nominal.clicked.connect(self._set_nominal)
        m.addWidget(set_nominal, 2, 2)
        self.maint_controls += [self.use_current_btn, self.nominal_spin, set_nominal]
        note = QLabel(f"Only the program's reference changes: nothing is sent to the DG645 and "
                      f"{self.ch} stays where it is. The allowed range "
                      f"({self.min_us:+.1f} … {self.max_us:+.1f} µs) and “Back to nominal” "
                      f"move with the nominal value.")
        note.setWordWrap(True)
        set_role(note, "muted")
        m.addWidget(note, 3, 0, 1, 4)
        m.setColumnStretch(3, 1)
        self.maint.hide()
        self.body.addWidget(self.maint)

    def _toggle_maintenance(self, on: bool) -> None:
        self.maint.setVisible(on)
        self.maint_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def _nominal(self) -> float:
        return float(self.state.get("nominal_s", self.nominal_s))

    def _use_current(self) -> None:
        cur = self.state.get("delay_s")
        if cur is None:
            return
        if self.confirm("Nominal value", f"Use the current {self.ch} as the nominal value?\n\n"
                        f"Old: T0 + {ms_text(self._nominal())}\nNew: T0 + {ms_text(cur)}\n\n"
                        f"Nothing is sent to the DG645. The allowed range moves with it."):
            self.run("use_current_as_nominal")

    def _set_nominal(self) -> None:
        new_ms = self.nominal_spin.value()
        if self.confirm("Nominal value", f"Change the nominal value of {self.ch}?\n\n"
                        f"Old: T0 + {ms_text(self._nominal())}\nNew: T0 + {ms_text(new_ms * 1e-3)}"
                        f"\n\nNothing is sent to the DG645. The allowed range moves with it."):
            self.run("set_nominal", nominal_ms=new_ms)

    def _button(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(slot)
        self.controls.append(b)
        return b

    def _step(self, sign: int) -> None:
        self.run("step", delta_us=sign * self.step_us)

    def busy_text(self, action: str) -> str:
        return BUSY_TEXT.get(action, super().busy_text(action).rstrip(" …")) + " …"

    def on_action_done(self, action: str, result: Any) -> None:
        if action == "connect":
            self._init_editor = True  # start the editors from the device's values
        elif action in ("set_offset", "step") and isinstance(result, dict):
            self.spin.setValue(float(result.get("new_us", self.spin.value())))
        elif action in ("set_nominal", "use_current_as_nominal") and isinstance(result, dict):
            new = float(result["new_s"])
            self.nominal_spin.setValue(new * 1e3)
            cur = self.state.get("delay_s")
            if cur is not None:  # C itself did not move; its offset from the new nominal
                self.spin.setValue(min(max((cur - new) * 1e6, self.min_us), self.max_us))

    def update_view(self) -> None:
        st = self.state if self.connected else {}
        offset_s = st.get("offset_s")
        problems = list(st.get("problems") or [])
        nominal = float(st.get("nominal_s", self.nominal_s))
        read_at = st.get("read_at")
        self.read_note.setText((f"Values read at {str(read_at)[11:19]}. " if read_at else "")
                               + self._read_note_text)
        self.unlock_btn.setEnabled(self.can_act)
        self.read_btn.setEnabled(self.can_act)
        self.limits_label.setText(
            f"Allowed: {self.min_us:+.1f} … {self.max_us:+.1f} µs from nominal "
            f"(T0 + {ms_text(nominal)}). {self.width_ch} moves with {self.ch}, so the pulse "
            f"width stays the same. A change acts at once (one trigger cycle may be cut short, "
            f"as with the front-panel knob).")
        saved_nominal = st.get("nominal")
        if not st:
            self.nominal_label.setText("—")
        elif saved_nominal:
            by = f" by {saved_nominal['by']}" if saved_nominal.get("by") else ""
            self.nominal_label.setText(f"T0 + {ms_text(nominal)}   (set{by}, "
                                       f"{_when(saved_nominal.get('at'))})")
        else:
            self.nominal_label.setText(f"T0 + {ms_text(nominal)}   (from the configuration file)")
        if offset_s is None:
            self.offset_label.setText("—")
            self.offset_label.setStyleSheet(f"font-size: 28pt; color:{C.GREY}")
            self.abs_label.setText("")
            self.last_label.setText("")
        else:
            off_us = offset_s * 1e6
            self.offset_label.setText(f"{us_text(offset_s)}  from nominal")
            self.offset_label.setStyleSheet(
                f"font-size: 28pt; color:{C.ORANGE}" if problems else "font-size: 28pt;")
            width = st.get("width_s")
            wtext = (f"{self.width_ch} = {self.ch} + {us_text(width, sign=False)} "
                     f"(pulse width, moves with {self.ch})" if width is not None else "")
            self.abs_label.setText(f"{self.ch} = T0 + {ms_text(st['delay_s'])}    ·    "
                                   f"nominal T0 + {ms_text(nominal)}    ·    {wtext}")
            if getattr(self, "_init_editor", False):
                self._init_editor = False
                self.spin.setValue(min(max(off_us, self.min_us), self.max_us))
                self.nominal_spin.setValue(nominal * 1e3)
            self.last_label.setText(self._last_change_text(st))
        if st.get("changed_outside"):
            last = st.get("last_set") or {}
            problems.append(
                f"{self.ch} is not the value this program set last "
                f"({us_text(float(last['delay_s']) - nominal)}, {_when(last.get('at'))}): "
                f"it was changed on the front panel, or the DG645 was switched off and on "
                f"(it then returns to its last front-panel setting).")
        self.warn_label.setText("\n".join(problems))
        self.warn_label.setStyleSheet(f"color:{C.ORANGE}")
        self.warn_label.setVisible(bool(problems))

        blocked = any("will not change" in p for p in st.get("problems") or [])
        ok = self.can_act and offset_s is not None and not blocked
        for w in self.controls:
            w.setEnabled(ok)
        # the nominal value can be changed even when C is outside the range (that may be why)
        for w in self.maint_controls:
            w.setEnabled(self.can_act and offset_s is not None)
        if ok:
            off_us = offset_s * 1e6
            self.minus_btn.setEnabled(off_us - self.step_us >= self.min_us - EPS_US)
            self.plus_btn.setEnabled(off_us + self.step_us <= self.max_us + EPS_US)
            self.nominal_btn.setEnabled(abs(off_us) > EPS_US)
        self.minus_btn.setToolTip("" if self.minus_btn.isEnabled() or not ok
                                  else f"Lower limit {self.min_us:+.1f} µs")
        self.plus_btn.setToolTip("" if self.plus_btn.isEnabled() or not ok
                                 else f"Upper limit {self.max_us:+.1f} µs")

        channels = st.get("channels") or {}
        for ch, (_name, rel, absolute) in self.rows.items():
            info = channels.get(ch)
            if info is None:
                rel.setText("—")
                absolute.setText("—")
            else:
                rel.setText(delay_text(info["ref"], info["delay_s"]))
                absolute.setText(ms_text(info["abs_s"]))

    def _last_change_text(self, st: dict[str, Any]) -> str:
        last = st.get("last_change")
        if not last:
            return ""
        nominal = st.get("nominal_s", self.nominal_s)
        if "old_s" in last and "new_s" in last:  # shown from the current nominal value
            old_s, new_s = last["old_s"] - nominal, last["new_s"] - nominal
        else:
            old_s, new_s = last["old_us"] * 1e-6, last["new_us"] * 1e-6
        what = f"{us_text(old_s)} → {us_text(new_s)}"
        if last.get("outside"):
            return f"Last change: {what}, outside the program (noticed {_when(last.get('at'))})"
        by = f" by {last['by']}" if last.get("by") else ""
        return f"Last change: {what}{by}, {_when(last.get('at'))}"
