"""Animated star field + comet background widget.

StarfieldBackground is a QWidget subclass intended to be used as the
central widget of a QMainWindow. Place all content widgets inside it
via a QVBoxLayout/QHBoxLayout; they will render on top of the
animated background with glass-effect rgba stylesheets.

Animation matches the visual design from the ui-son- reference project:
  • 140 drifting stars with sinusoidal glow
  • Shooting stars / comets with 26-point fade trail
  • Deep-space gradient: #020617 → #0f172a
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

_STAR_COUNT = 140
_COMET_SPAWN_CHANCE = 0.05
_MAX_COMETS = 6


class StarfieldBackground(QWidget):
    """QWidget that paints an animated starfield + comet background.

    Usage::

        bg = StarfieldBackground(self)
        self.setCentralWidget(bg)
        layout = QVBoxLayout(bg)
        layout.addWidget(my_panel)  # glass-styled panels go here
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(False)

        self._stars: list[dict] = [
            {
                "x":     random.uniform(0, 1500),
                "y":     random.uniform(0, 900),
                "speed": random.uniform(0.25, 0.9),
                "size":  random.uniform(1.0, 2.6),
                "phase": random.uniform(0, math.pi * 2),
            }
            for _ in range(_STAR_COUNT)
        ]
        self._comets: list[dict] = []

        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------ animation

    def _tick(self) -> None:
        w = max(self.width(), 800)
        h = max(self.height(), 600)

        for s in self._stars:
            s["y"] += s["speed"]
            s["phase"] += 0.06
            if s["y"] > h:
                s["y"] = 0
                s["x"] = random.uniform(0, w)

        if random.random() < _COMET_SPAWN_CHANCE and len(self._comets) < _MAX_COMETS:
            self._comets.append({
                "x":    random.uniform(0, w),
                "y":    random.uniform(0, h * 0.5),
                "vx":   random.uniform(10, 18),
                "vy":   random.uniform(4, 8),
                "life": 30,
            })

        for c in self._comets:
            c["x"] += c["vx"]
            c["y"] += c["vy"]
            c["life"] -= 1
        self._comets = [c for c in self._comets if c["life"] > 0]

        self.update()

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:  # noqa: N802
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Background gradient ──────────────────────────────────────────────
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor("#020617"))
        grad.setColorAt(1, QColor("#0f172a"))
        p.fillRect(0, 0, w, h, grad)

        # ── Stars ────────────────────────────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        for s in self._stars:
            glow = (math.sin(s["phase"]) + 1) / 2
            alpha = int(100 + glow * 140)
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawEllipse(
                int(s["x"]), int(s["y"]),
                int(s["size"]), int(s["size"]),
            )

        # ── Comets / shooting stars ──────────────────────────────────────────
        for c in self._comets:
            for i in range(26):
                alpha = int(255 * (1 - i / 26))
                pen = QPen(QColor(180, 220, 255, alpha))
                pen.setWidth(5 if i < 5 else 3)
                p.setPen(pen)
                p.drawPoint(
                    int(c["x"] - i * 7),
                    int(c["y"] - i * 3),
                )

    def stop_animation(self) -> None:
        """Stop the animation timer (call on window close to free resources)."""
        self._timer.stop()
