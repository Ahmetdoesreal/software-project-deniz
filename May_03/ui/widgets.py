"""Factory functions for styled PySide6 widgets (Sovereign Sentinel theme).

Usage pattern
-------------
    from ui.widgets import apply_theme, make_button, make_label, make_card

    # In run() / main():
    app = QApplication(sys.argv)
    apply_theme(app)

    # In _build_layout():
    btn = make_button("Start", "filled")
    btn.clicked.connect(handler)
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from ui.styles import (
    GLOBAL_QSS,
    btn_filled,
    btn_outlined,
    btn_text,
    btn_tonal,
    card_elevated,
    card_filled,
    card_outlined,
)
from ui.theme import M, TY, apply_typography

_BTN_STYLES: dict[str, object] = {
    "filled":   btn_filled,
    "tonal":    btn_tonal,
    "outlined": btn_outlined,
    "text":     btn_text,
}


def apply_theme(app: QApplication) -> None:
    """Apply the global Sovereign Sentinel stylesheet to *app*."""
    app.setStyleSheet(GLOBAL_QSS)


def make_button(
    text: str,
    variant: str = "tonal",
    parent: QWidget | None = None,
) -> QPushButton:
    """Return a styled QPushButton.

    variant: "filled" | "tonal" | "outlined" | "text"
    """
    btn = QPushButton(text, parent)
    style_button(btn, variant)
    return btn


def style_button(btn: QPushButton, variant: str = "tonal") -> None:
    """Apply a button variant stylesheet to an existing QPushButton."""
    style_fn = _BTN_STYLES.get(variant, btn_tonal)
    btn.setStyleSheet(style_fn())  # type: ignore[call-arg]
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))


def make_label(
    text: str,
    role: str = "body_large",
    color: str | None = None,
    parent: QWidget | None = None,
) -> QLabel:
    """Return a QLabel styled with the given typography role and colour."""
    label = QLabel(text, parent)
    apply_typography(label, role)
    c = color or M["on_surface"]
    label.setStyleSheet(f"color: {c}; background: transparent;")
    return label


def make_card(
    variant: str = "elevated",
    parent: QWidget | None = None,
) -> QFrame:
    """Return a styled QFrame suitable as a card container.

    variant: "elevated" | "filled" | "outlined"
    """
    frame = QFrame(parent)
    styles = {
        "elevated": card_elevated,
        "filled":   card_filled,
        "outlined": card_outlined,
    }
    style_fn = styles.get(variant, card_elevated)
    frame.setStyleSheet(f"QFrame {{ {style_fn()} }}")
    return frame


def make_divider(
    vertical: bool = False,
    parent: QWidget | None = None,
) -> QFrame:
    """Return a 1-px tonal separator line."""
    line = QFrame(parent)
    if vertical:
        line.setFixedWidth(1)
        line.setSizePolicy(
            line.sizePolicy().horizontalPolicy(),
            line.sizePolicy().verticalPolicy(),
        )
    else:
        line.setFixedHeight(1)
    line.setStyleSheet(
        f"background-color: {M['surface_container_high']}; border: none;"
    )
    return line


def make_console(parent: QWidget | None = None) -> QPlainTextEdit:
    """Return a read-only, monospace console output widget."""
    widget = QPlainTextEdit(parent)
    widget.setReadOnly(True)
    widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    widget.setStyleSheet(
        f"background: {M['surface_container_lowest']}; "
        f"color: {M['on_surface']}; "
        "font-family: 'Cascadia Code', 'JetBrains Mono', 'Consolas', monospace; "
        "font-size: 12px; "
        "border: none; "
        f"selection-background-color: {M['primary_container']};"
    )
    return widget


def monospace_font():
    """Return the system monospace font (convenience re-export)."""
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
