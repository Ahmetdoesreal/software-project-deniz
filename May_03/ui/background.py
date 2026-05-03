"""Animated star field + comet background widget.

StarfieldBackground is a QWidget subclass intended to be used as the
central widget of a QMainWindow. Place all content widgets inside it
via a QVBoxLayout/QHBoxLayout; they will render on top of the
animated background with glass-effect rgba stylesheets.
"""

from __future__ import annotations

import math
import random
import sys
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

_STAR_COUNT = 240
_COMET_SPAWN_CHANCE = 0.05
_MAX_COMETS = 6
_COMET_LIFE = 30


def _dbg(msg: str) -> None:
    print(f"[STARFIELD] {msg}", file=sys.stderr, flush=True)


class StarfieldBackground(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        _dbg("__init__ start")
        try:
            super().__init__(parent)
            self.setAutoFillBackground(False)

            screen = QGuiApplication.primaryScreen()
            sw = screen.geometry().width() if screen else 800
            sh = screen.geometry().height() if screen else 600
            _dbg(f"screen size: {sw}x{sh}")

            self._stars: list[dict] = [
                {
                    "x":     random.uniform(0, sw),
                    "y":     random.uniform(0, sh),
                    "speed": random.uniform(0.25, 0.9),
                    "size":  random.uniform(2.0, 3.6),
                    "phase": random.uniform(0, math.pi * 2),
                }
                for _ in range(_STAR_COUNT)
            ]
            self._comets: list[dict] = []
            self._tick_count = 0
            self._paint_count = 0

            self._timer = QTimer(self)
            self._timer.setInterval(25)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
            _dbg("__init__ done, timer started")
        except Exception:
            _dbg(f"__init__ EXCEPTION:\n{traceback.format_exc()}")
            raise

    # ------------------------------------------------------------------ animation

    def _tick(self) -> None:
        self._tick_count += 1
        try:
            if not self.isVisible():
                return
            w = self.width()
            h = self.height()
            if w <= 0 or h <= 0:
                return

            if self._tick_count % 200 == 0:
                _dbg(f"tick={self._tick_count} paint={self._paint_count} "
                     f"size={w}x{h} stars={len(self._stars)} comets={len(self._comets)}")

            for s in self._stars:
                s["y"] += s["speed"]
                s["phase"] += 0.06
                if s["y"] > h:
                    s["y"] = 0
                    s["x"] = random.uniform(0, w)

            if random.random() < _COMET_SPAWN_CHANCE and len(self._comets) < _MAX_COMETS:
                if random.random() < 0.5:
                    x = random.uniform(-60, -10)
                    y = random.uniform(0, h * 0.7)
                else:
                    x = random.uniform(0, w * 0.7)
                    y = random.uniform(-30, -10)
                self._comets.append({
                    "x":    x,
                    "y":    y,
                    "vx":   random.uniform(10, 18),
                    "vy":   random.uniform(4, 8),
                    "life": _COMET_LIFE,
                })

            for c in self._comets:
                c["x"] += c["vx"]
                c["y"] += c["vy"]
                c["life"] -= 1
            self._comets = [c for c in self._comets if c["life"] > 0]

            self.update()
        except Exception:
            _dbg(f"_tick EXCEPTION at tick={self._tick_count}:\n{traceback.format_exc()}")

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:  # noqa: N802
        self._paint_count += 1
        try:
            w, h = self.width(), self.height()
            if w <= 0 or h <= 0:
                return

            if self._paint_count <= 3:
                _dbg(f"paintEvent #{self._paint_count} size={w}x{h}")

            p = QPainter(self)
            if not p.isActive():
                _dbg(f"paintEvent #{self._paint_count}: painter not active, skipping")
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0, QColor("#020617"))
            grad.setColorAt(1, QColor("#0f172a"))
            p.fillRect(0, 0, w, h, grad)

            p.setPen(Qt.PenStyle.NoPen)
            for s in self._stars:
                glow = (math.sin(s["phase"]) + 1) / 2
                alpha = int(100 + glow * 140)
                p.setBrush(QColor(255, 255, 255, alpha))
                p.drawEllipse(
                    int(s["x"]), int(s["y"]),
                    int(s["size"]), int(s["size"]),
                )

            for c in self._comets:
                life_frac = c["life"] / _COMET_LIFE
                for i in range(26):
                    alpha = int(255 * (1 - i / 26) * life_frac)
                    if alpha <= 0:
                        continue
                    pen = QPen(QColor(180, 220, 255, alpha))
                    pen.setWidth(5 if i < 5 else 3)
                    p.setPen(pen)
                    p.drawPoint(
                        int(c["x"] - i * 7),
                        int(c["y"] - i * 3),
                    )

            p.end()
        except Exception:
            _dbg(f"paintEvent EXCEPTION at paint={self._paint_count}:\n{traceback.format_exc()}")

    # ------------------------------------------------------------------ lifecycle

    def closeEvent(self, event) -> None:  # noqa: N802
        _dbg("closeEvent: stopping timer")
        self._timer.stop()
        super().closeEvent(event)

    def stop_animation(self) -> None:
        _dbg("stop_animation called")
        self._timer.stop()
