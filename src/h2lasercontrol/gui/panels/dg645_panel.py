"""Delay generator tab (SRS DG645): adjust our laser-trigger edge (C) in µs around nominal, within
hard limits; every channel shown read-only (user 2026-11-20, design-document F3b-F3g)."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...drivers.dg645 import WATCHED, delay_text, ms_text, us_text
from ..style import C, set_role
from .base import DevicePanel

BUSY_TEXT = {"set_offset": "Setting the trigger delay", "step": "Stepping the trigger delay"}
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

        limits = QLabel(f"Allowed: {self.min_us:+.1f} … {self.max_us:+.1f} µs from nominal "
                        f"(T0 + {ms_text(self.nominal_s)}). {self.width_ch} moves with "
                        f"{self.ch}, so the pulse width stays the same. A change acts at once "
                        f"(one trigger cycle may be cut short, as with the front-panel knob).")
        limits.setWordWrap(True)
        set_role(limits, "muted")
        g.addWidget(limits, 2, 0, 1, 5)
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
            name = QLabel(f"{ch}  (ours)" if ours else ch)
            rel, absolute = QLabel("—"), QLabel("—")
            for col, w in enumerate((name, rel, absolute)):
                if ours:
                    w.setStyleSheet("font-weight: bold;")
                a.addWidget(w, i, col)
            self.rows[ch] = (name, rel, absolute)
        a.setColumnStretch(3, 1)
        self.body.addWidget(allbox)
        note = QLabel("Changes made on the front panel are noticed within a few seconds and "
                      "written to the operation history.")
        note.setWordWrap(True)
        set_role(note, "muted")
        self.body.addWidget(note)

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
        if action == "connect":  # start the editor from the device's value
            self._init_editor = True
        elif action in ("set_offset", "step") and isinstance(result, dict):
            self.spin.setValue(float(result.get("new_us", self.spin.value())))

    def update_view(self) -> None:
        st = self.state if self.connected else {}
        offset_s = st.get("offset_s")
        problems = list(st.get("problems") or [])
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
                                   f"nominal T0 + {ms_text(self.nominal_s)}    ·    {wtext}")
            if getattr(self, "_init_editor", False):
                self._init_editor = False
                self.spin.setValue(min(max(off_us, self.min_us), self.max_us))
            self.last_label.setText(self._last_change_text(st))
        if st.get("changed_outside"):
            last = st.get("last_set") or {}
            problems.append(
                f"{self.ch} is not the value this program set last "
                f"({us_text(float(last['delay_s']) - self.nominal_s)}, {_when(last.get('at'))}): "
                f"it was changed on the front panel, or the DG645 was switched off and on "
                f"(it then returns to its last front-panel setting).")
        self.warn_label.setText("\n".join(problems))
        self.warn_label.setStyleSheet(f"color:{C.ORANGE}")
        self.warn_label.setVisible(bool(problems))

        blocked = any("will not change" in p for p in st.get("problems") or [])
        ok = self.can_act and offset_s is not None and not blocked
        for w in self.controls:
            w.setEnabled(ok)
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
        what = f"{us_text(last['old_us'] * 1e-6)} → {us_text(last['new_us'] * 1e-6)}"
        if last.get("outside"):
            return f"Last change: {what}, outside the program (noticed {_when(last.get('at'))})"
        by = f" by {last['by']}" if last.get("by") else ""
        return f"Last change: {what}{by}, {_when(last.get('at'))}"
