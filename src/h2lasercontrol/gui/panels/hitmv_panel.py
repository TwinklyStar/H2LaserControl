"""HIT-MV tab: one card per linear feedthrough with Insert / Retract."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..style import C, set_role
from .base import DevicePanel

DEFAULT_UNITS_PER_MM = 500000  # our stages: 30000000 units = 60 mm real (1 unit = 2 nm)


class AxisCard(QGroupBox):
    def __init__(self, panel: HitMvPanel, axis: int, label: str, inserted: int, retracted: int):
        super().__init__(label)
        self.panel = panel
        self.axis = axis
        self.label = label
        self.inserted = inserted
        self.retracted = retracted

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        self.state_label = QLabel("—")
        set_role(self.state_label, "big")
        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.pos_label = QLabel()
        set_role(self.pos_label, "muted")
        self.alarm_label = QLabel()
        set_role(self.alarm_label, "alarm")
        self.alarm_label.hide()

        buttons = QHBoxLayout()
        self.insert_btn = QPushButton("Insert")
        self.retract_btn = QPushButton("Retract")
        for b in (self.insert_btn, self.retract_btn):
            set_role(b, "primary")
            buttons.addWidget(b)
        # no confirmation dialog for insert (user, 2026-11-18)
        self.insert_btn.clicked.connect(lambda: panel.axis_action("insert", self.axis))
        self.retract_btn.clicked.connect(lambda: panel.axis_action("retract", self.axis))

        for w in (self.state_label, self.hint_label, self.bar, self.pos_label, self.alarm_label):
            lay.addWidget(w)
        lay.addSpacing(6)
        lay.addLayout(buttons)

    def display(self, info: dict[str, Any] | None, *, can_act: bool, moving: str | None,
                elapsed: float | None, blocked_by: str | None = None,
                positions_lost: bool = False) -> None:
        """`blocked_by`: label of another feedthrough that is not retracted (interlock F2a:
        never two inserted at once) -> Insert is disabled. Retract is only blocked when
        `positions_lost` (all axes read 0 after a controller restart): then nothing may move."""
        pos = None if info is None else info.get("position")
        upmm = self.panel.units_per_mm
        if positions_lost and pos is not None and not moving:
            self._set_state("POSITION UNKNOWN", C.RED,
                            "The controller was restarted: its position reading (0) is not "
                            "the real position. Check by eye, then home and retract with "
                            "HIT Sample (ORG). Insert/Retract are locked until then.")
            self.pos_label.setText(f"Controller reads {pos / upmm:.2f} mm (not valid)")
            self.bar.setValue(0)
            self.insert_btn.setEnabled(False)
            self.retract_btn.setEnabled(False)
            tip = "Locked: position unknown after a controller restart"
            self.insert_btn.setToolTip(tip)
            self.retract_btn.setToolTip(tip)
            alarms = (info or {}).get("alarms") or []
            self.alarm_label.setText("Alarm: " + ", ".join(alarms) if alarms else "")
            self.alarm_label.setVisible(bool(alarms))
            return
        if pos is None:
            self._set_state("—", C.GREY, "No data" if not self.panel.connected else "Axis not connected")
            self.pos_label.setText("")
            self.bar.setValue(0)
        else:
            span = self.retracted - self.inserted
            self.bar.setValue(int(1000 * (self.retracted - pos) / span) if span else 0)
            self.pos_label.setText(
                f"Position {pos / upmm:.2f} mm   (0 mm = inserted, {self.retracted / upmm:.0f} mm = retracted)"
            )
            if moving:
                verb = {"insert": "Inserting", "retract": "Retracting"}.get(moving, "Moving")
                t = f" ({elapsed:.0f} s so far)" if elapsed is not None else ""
                self._set_state(f"{verb} …", C.BLUE, f"Moving{t}, about 30 s in total. "
                                "Press STOP to stop.")
            elif pos == self.retracted and blocked_by:
                self._set_state("RETRACTED", C.GREEN,
                                f"🔒 Locked: retract the {blocked_by} first "
                                "(the two must never be inserted together).")
            elif pos == self.retracted:
                self._set_state("RETRACTED", C.GREEN, "Out of the beam (normal state).")
            elif pos == self.inserted:
                self._set_state("INSERTED", C.ORANGE, "In the beam: the 122 nm beam does not reach the target.")
            else:
                self._set_state("PARTLY INSERTED", C.ORANGE,
                                "Stopped between the ends: choose Insert or Retract.")
        alarms = (info or {}).get("alarms") or []
        self.alarm_label.setText("Alarm: " + ", ".join(alarms) if alarms else "")
        self.alarm_label.setVisible(bool(alarms))

        connected_axis = pos is not None
        self.insert_btn.setEnabled(can_act and connected_axis and pos != self.inserted
                                   and not blocked_by)
        self.retract_btn.setEnabled(can_act and connected_axis and pos != self.retracted)
        self.insert_btn.setToolTip(
            f"Locked: the {blocked_by} is not retracted. Retract it first." if blocked_by else
            "Already inserted" if pos == self.inserted else "Move into the beam (origin return)"
        )
        self.retract_btn.setToolTip("Already retracted" if pos == self.retracted else
                                    "Move out of the beam")

    def _set_state(self, text: str, color: str, hint: str) -> None:
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color:{color}")
        self.hint_label.setText(hint)
        self.bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")


class HitMvPanel(DevicePanel):
    def build_body(self) -> None:
        s = self.cfg.settings
        self.units_per_mm = int(s.get("units_per_mm", DEFAULT_UNITS_PER_MM))
        self.moving: tuple[int, str] | None = None
        self.progress_info: dict[str, Any] = {}
        row = QHBoxLayout()
        row.setSpacing(16)
        self.cards: dict[int, AxisCard] = {}
        self.axis_names: dict[int, str] = {}
        for num, a in sorted(s.get("axes", {}).items(), key=lambda kv: int(kv[0])):
            pos = a.get("positions", {})
            n = int(num)
            self.axis_names[n] = a["name"]
            card = AxisCard(self, n, a.get("label", a["name"]), int(pos.get("INSERTED", 0)),
                            int(pos.get("RETRACTED", 30000000)))
            self.cards[n] = card
            row.addWidget(card)
        self.body.addLayout(row)
        note = QLabel("Insert takes about 30 s, retract about 30 s. Both feedthroughs are normally "
                      "retracted, and only one may be inserted at a time.")
        set_role(note, "muted")
        self.body.addWidget(note)

    def busy_text(self, action: str) -> str:
        name = self.cards[self.moving[0]].label if self.moving else ""
        verb = {"insert": "Inserting", "retract": "Retracting"}.get(action)
        return f"{verb} {name} …" if verb else super().busy_text(action)

    def axis_action(self, action: str, axis: int) -> None:
        if not self.can_act:
            return
        self.moving = (axis, action)
        self.progress_info = {}
        self.run(action, axis=axis)

    def _on_busy(self, busy: bool, action: str) -> None:
        self._busy_action = action
        super()._on_busy(busy, action)

    def on_progress(self, info: dict) -> None:
        self.progress_info = info
        if self.moving is None and self.busy and "axis" in info:
            # a move started elsewhere (Shifter tab, F9): show it like our own
            action = getattr(self, "_busy_action", "")
            self.moving = (info["axis"], action)
            self.busy_label.setText(self.busy_text(action))
        self.update_view()

    def update_view(self) -> None:
        axes = self.state.get("axes", {})
        if not self.busy:
            self.moving = None
        exclusive = bool(self.cfg.settings.get("exclusive_axes", True))
        lost = bool(self.connected and self.state.get("positions_lost"))
        # axes that are not exactly retracted (or are moving / unknown) lock the others
        not_retracted = set()
        for n, card in self.cards.items():
            info = axes.get(self.axis_names[n]) or {}
            if info.get("position") != card.retracted or info.get("busy") or (
                    self.moving and self.moving[0] == n):
                not_retracted.add(n)
        for n, card in self.cards.items():
            others = [self.cards[o].label for o in sorted(not_retracted) if o != n]
            blocked_by = " and ".join(others) if exclusive and self.connected and others else None
            info = dict(axes.get(self.axis_names[n]) or {}) if self.connected else None
            moving = elapsed = None
            if self.moving and self.moving[0] == n:
                moving = self.moving[1]
                if self.progress_info.get("axis") == n:
                    info = {**(info or {}), "position": self.progress_info["position"]}
                    elapsed = self.progress_info.get("elapsed")
            card.display(info, can_act=self.can_act, moving=moving, elapsed=elapsed,
                         blocked_by=blocked_by, positions_lost=lost)
