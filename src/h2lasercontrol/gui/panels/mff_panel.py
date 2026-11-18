"""Flip mounts tab (Thorlabs MFF101): one card per unit with Insert / Retract, like the HIT-MV tab.

A unit that is not plugged in shows "NOT CONNECTED" on its card (the program retries it every few
seconds); the other units keep working.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..style import C, set_role
from .base import DevicePanel


class FlipCard(QGroupBox):
    def __init__(self, panel: MffPanel, key: str, label: str):
        super().__init__(label)
        self.panel = panel
        self.key = key
        self.label = label

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        self.state_label = QLabel("—")
        set_role(self.state_label, "big")
        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)

        buttons = QHBoxLayout()
        self.insert_btn = QPushButton("Insert")
        self.retract_btn = QPushButton("Retract")
        for b in (self.insert_btn, self.retract_btn):
            set_role(b, "primary")
            buttons.addWidget(b)
        self.insert_btn.clicked.connect(lambda: panel.unit_action("insert", key))
        self.retract_btn.clicked.connect(lambda: panel.unit_action("retract", key))

        self.led_btn = QPushButton("Flash LED")
        self.led_btn.setFlat(True)
        self.led_btn.setToolTip("Blink this flip mount's LED, to see which physical unit it is")
        self.led_btn.clicked.connect(lambda: panel.run("flash_led", unit=key))
        led_row = QHBoxLayout()
        led_row.addStretch(1)
        led_row.addWidget(self.led_btn)

        lay.addWidget(self.state_label)
        lay.addWidget(self.hint_label)
        lay.addSpacing(6)
        lay.addLayout(buttons)
        lay.addLayout(led_row)

    def display(self, info: dict[str, Any] | None, *, can_act: bool, moving: str | None) -> None:
        online = bool(info and info.get("connected"))
        pos = info.get("position") if online and info else None
        if info is None:
            self._set_state("—", C.GREY, "No data" if self.panel.connected else "Not connected")
        elif not online:
            err = info.get("error") or "not connected"
            self._set_state("NOT CONNECTED", C.GREY,
                            f"{err}\nThe program tries again every few seconds.")
        elif moving or info.get("moving"):
            verb = {"insert": "Inserting", "retract": "Retracting"}.get(moving or "", "Moving")
            self._set_state(f"{verb} …", C.BLUE, "Flipping (about half a second).")
        elif pos == "insert":
            self._set_state("INSERTED", C.ORANGE, "Flipped into the beam path.")
        elif pos == "retract":
            self._set_state("RETRACTED", C.GREEN, "Flipped out of the beam path.")
        else:
            self._set_state("BETWEEN POSITIONS", C.ORANGE,
                            "Neither position is reached: choose Insert or Retract.")
        ok = can_act and online
        self.insert_btn.setEnabled(ok and pos != "insert")
        self.retract_btn.setEnabled(ok and pos != "retract")
        self.led_btn.setEnabled(ok)
        self.insert_btn.setToolTip("Already inserted" if pos == "insert" else
                                   "Flip into the beam path")
        self.retract_btn.setToolTip("Already retracted" if pos == "retract" else
                                    "Flip out of the beam path")

    def _set_state(self, text: str, color: str, hint: str) -> None:
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color:{color}")
        self.hint_label.setText(hint)


class MffPanel(DevicePanel):
    def build_body(self) -> None:
        self.moving: tuple[str, str] | None = None
        row = QHBoxLayout()
        row.setSpacing(16)
        self.cards: dict[str, FlipCard] = {}
        for key, u in self.cfg.settings.get("units", {}).items():
            card = FlipCard(self, key, u.get("label", key))
            self.cards[key] = card
            row.addWidget(card)
        self.body.addLayout(row)
        note = QLabel("A flip takes about half a second. Close Kinesis before connecting: the two "
                      "programs cannot use the flip mounts at the same time.")
        note.setWordWrap(True)
        set_role(note, "muted")
        self.body.addWidget(note)
        # a flip cannot be stopped halfway (it takes 0.5 s), so STOP is not offered here
        self.stop_btn.hide()

    def busy_text(self, action: str) -> str:
        name = self.cards[self.moving[0]].label if self.moving else ""
        verb = {"insert": "Inserting", "retract": "Retracting"}.get(action)
        return f"{verb} {name} …" if verb else super().busy_text(action)

    def unit_action(self, action: str, key: str) -> None:
        if not self.can_act:
            return
        self.moving = (key, action)
        self.run(action, unit=key)

    def update_view(self) -> None:
        units = self.state.get("units", {})
        if not self.busy:
            self.moving = None
        for key, card in self.cards.items():
            info = units.get(key) if self.connected else None
            moving = self.moving[1] if self.moving and self.moving[0] == key else None
            card.display(info, can_act=self.can_act, moving=moving)
