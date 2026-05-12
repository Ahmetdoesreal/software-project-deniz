"""QSS stylesheet strings for the Sovereign Sentinel design system.

All functions return stylesheet strings that can be passed to
``widget.setStyleSheet()`` or ``QApplication.setStyleSheet()``.
"""

from __future__ import annotations

from pathlib import Path

from ui.theme import M, SHAPE, STATE_COLORS

# Path to checkmark SVG for checkbox indicators (QSS needs forward slashes)
_CHECKMARK_SVG = str(Path(__file__).resolve().parent / "checkmark.svg").replace("\\", "/")

# ── Global stylesheet ─────────────────────────────────────────────────────────
GLOBAL_QSS = f"""
* {{
    font-family: "Inter", "Public Sans", "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
    color: {M['on_surface']};
}}
QMainWindow, QDialog, QWidget {{
    background-color: {M['background']};
}}
/* ─ Group boxes: tonal surface, no native border ─ */
QGroupBox {{
    background-color: {M['surface_container']};
    border: none;
    border-radius: {SHAPE['medium']}px;
    margin-top: 22px;
    padding: 8px 6px 6px 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {M['on_surface_variant']};
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.5px;
}}
/* ─ Scrollbars: minimal ─ */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 6px; margin: 4px 0;
}}
QScrollBar::handle:vertical {{
    background: {M['outline_variant']}; border-radius: 3px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {M['outline']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 6px; margin: 0 4px;
}}
QScrollBar::handle:horizontal {{
    background: {M['outline_variant']}; border-radius: 3px; min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
/* ─ Tables: flat, column separators ─ */
QTableWidget {{
    background: transparent;
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: transparent;
}}
QTableWidget::item {{
    padding: 4px 10px;
    border: none;
    border-right: 1px solid {M['surface_container']};
}}
QTableWidget::item:selected {{
    background: {M['primary_container']};
    color: {M['on_surface']};
}}
QTableWidget::item:hover:!selected {{
    background: transparent;
}}
/* ─ Tree widget ─ */
QTreeWidget {{
    background: {M['surface_container_low']};
    border: none;
    outline: none;
}}
QTreeWidget::item {{
    padding: 3px 6px;
    color: {M['on_surface']};
}}
QTreeWidget::item:selected {{
    background: {M['primary_container']};
    color: {M['on_surface']};
}}
QTreeWidget::item:hover:!selected {{
    background: transparent;
}}
/* ─ Headers ─ */
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: transparent;
    color: {M['on_surface_variant']};
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.5px;
    padding: 10px;
    border: none;
    border-right: 1px solid {M['surface_container']};
    border-bottom: 1px solid {M['surface_container']};
}}
QHeaderView::section:last {{ border-right: none; }}
/* ─ Line edit ─ */
QLineEdit {{
    background: {M['surface_container_low']};
    border: 1px solid {M['outline_variant']};
    border-radius: {SHAPE['small']}px;
    padding: 7px 15px;
    color: {M['on_surface']};
    font-size: 13px;
}}
QLineEdit:focus {{
    background: {M['surface_container']};
    border: 2px solid {M['outline']};
    padding: 6px 14px;
}}
QLineEdit:read-only {{ color: {M['on_surface_variant']}; }}
QLineEdit:disabled {{
    background: {M['surface_container_high']};
    color: {M['on_surface_variant']}88;
}}
/* ─ Spin box ─ */
QSpinBox {{
    background: {M['surface_container_low']};
    border: 1px solid {M['outline_variant']};
    border-radius: {SHAPE['small']}px;
    padding: 5px 8px;
    color: {M['on_surface']};
}}
QSpinBox:focus {{ border: 2px solid {M['outline']}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {M['surface_container_high']};
    border: none;
    width: 18px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {M['primary_container']};
}}
/* ─ Checkbox ─ */
QCheckBox {{
    color: {M['on_surface_variant']};
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 2px solid {M['outline_variant']};
    border-radius: {SHAPE['extra_small']}px;
    background: {M['surface_container_low']};
}}
QCheckBox::indicator:checked {{
    background: transparent;
    border-color: {M['primary']};
    image: url({_CHECKMARK_SVG});
}}
/* ─ Splitter ─ */
QSplitter::handle {{ background: {M['surface_container']}; }}
QSplitter::handle:hover {{ background: {M['primary']}44; }}
/* ─ Tabs ─ */
QTabWidget::pane {{
    border: none;
    background: {M['surface_container_low']};
}}
QTabBar {{ background: {M['surface_container']}; }}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 12px 20px;
    color: {M['on_surface_variant']};
    font-size: 13px;
    font-weight: 500;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    color: {M['primary']};
    border-bottom: 3px solid {M['primary']};
    background: {M['surface_container_low']};
}}
QTabBar::tab:hover:!selected {{
    color: {M['on_surface']};
    background: {M['surface_container']};
}}
/* ─ Status bar ─ */
QStatusBar {{
    background: {M['surface_container_lowest']};
    border: none;
    color: {M['on_surface_variant']};
    font-size: 11px;
    font-weight: 500;
    padding: 4px 16px;
}}
/* ─ Menus ─ */
QMenu {{
    background: {M['surface_container_highest']};
    border: none;
    border-radius: {SHAPE['small']}px;
}}
QMenu::item {{ padding: 8px 20px; color: {M['on_surface']}; font-size: 13px; }}
QMenu::item:selected {{ background: {M['primary_container']}; color: {M['on_surface']}; }}
/* ─ Tooltip ─ */
QToolTip {{
    background: {M['surface_container_highest']};
    border: none;
    border-radius: {SHAPE['small']}px;
    color: {M['on_surface']};
    padding: 6px 10px;
    font-size: 11px;
}}
/* ─ Plain / rich text areas ─ */
QPlainTextEdit, QTextEdit {{
    background: {M['surface_container_lowest']};
    border: none;
    color: {M['on_surface']};
    selection-background-color: {M['primary_container']};
}}
/* ─ Labels ─ */
QLabel {{ background: transparent; color: {M['on_surface']}; }}
/* ─ Dialog button box ─ */
QDialogButtonBox QPushButton {{ min-width: 80px; }}
"""


# ── Unified button style ──────────────────────────────────────────────────────
# All buttons share the same light-blue, bordered, white-gradient look.

def _unified_btn() -> str:
    """Light blue button with border and white gradient — used for ALL buttons."""
    return f"""
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.18),
        stop:0.45 rgba(173, 206, 255, 0.30),
        stop:1 rgba(120, 170, 240, 0.40));
    color: #ffffff;
    border: 1px solid rgba(177, 197, 255, 0.50);
    border-radius: {SHAPE['small']}px;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.1px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.28),
        stop:0.45 rgba(173, 206, 255, 0.42),
        stop:1 rgba(120, 170, 240, 0.55));
    border: 1px solid rgba(177, 197, 255, 0.70);
}}
QPushButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.10),
        stop:0.45 rgba(140, 180, 240, 0.35),
        stop:1 rgba(100, 150, 220, 0.50));
    border: 1px solid rgba(177, 197, 255, 0.60);
}}
QPushButton:disabled {{
    background: rgba(120, 170, 240, 0.12);
    color: rgba(177, 197, 255, 0.40);
    border: 1px solid rgba(177, 197, 255, 0.18);
}}
"""


def btn_filled() -> str:
    """Primary action — unified light-blue style."""
    return _unified_btn()


def btn_tonal() -> str:
    """Secondary action — unified light-blue style."""
    return _unified_btn()


def btn_outlined() -> str:
    """Low-emphasis action — unified light-blue style."""
    return _unified_btn()


def btn_text() -> str:
    """Tertiary action — unified light-blue style."""
    return _unified_btn()


# ── Card variants ─────────────────────────────────────────────────────────────

def card_elevated() -> str:
    return (
        f"background-color: {M['surface_container_high']}; "
        f"border: none; border-radius: {SHAPE['medium']}px;"
    )


def card_filled() -> str:
    return (
        f"background-color: {M['surface_container']}; "
        f"border: none; border-radius: {SHAPE['medium']}px;"
    )


def card_outlined() -> str:
    return (
        f"background-color: {M['surface_container_low']}; "
        f"border: none; border-radius: {SHAPE['medium']}px;"
    )


# ── Progress bar ──────────────────────────────────────────────────────────────

def md3_progress(color: str | None = None) -> str:
    fill = color or M["primary"]
    return f"""
QProgressBar {{
    background-color: {M['surface_container']};
    border-radius: 2px;
    border: none;
    height: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {fill};
    border-radius: 2px;
}}
"""


# ── Glass / starfield stylesheet (for server dashboard) ───────────────────────
# Used when StarfieldBackground is the central widget.
# All QWidget descendants are transparent by default; panels use rgba glass.

GLASS_QSS = """
* {
    font-family: "Inter", "Public Sans", "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
    color: #f8fafc;
}
QMainWindow {
    background-color: #020617;
}
QWidget {
    background: transparent;
    color: #f8fafc;
}
/* ─ Dialogs must stay opaque ─ */
QDialog {
    background-color: rgba(10, 16, 35, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 16px;
}
QDialogButtonBox QPushButton { min-width: 80px; }
/* ─ Glass group boxes ─ */
QGroupBox {
    background-color: rgba(15, 23, 42, 0.70);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 16px;
    margin-top: 22px;
    padding: 8px 6px 6px 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: rgba(248, 250, 252, 0.55);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}
/* ─ Scrollbars: minimal ─ */
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: transparent; width: 6px; margin: 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.15); border-radius: 3px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.30); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 6px; margin: 0 4px;
}
QScrollBar::handle:horizontal {
    background: rgba(255,255,255,0.15); border-radius: 3px; min-width: 32px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
/* ─ Tables ─ */
QTableWidget {
    background: rgba(2, 6, 23, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    gridline-color: transparent;
    outline: none;
    selection-background-color: transparent;
}
QTableWidget::item {
    padding: 4px 10px;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    color: #e2e8f0;
}
QTableWidget::item:selected {
    background: rgba(59, 130, 246, 0.15);
    color: #f8fafc;
}
QTableWidget::item:hover:!selected {
    background: transparent;
}
/* ─ Tree widget ─ */
QTreeWidget {
    background: rgba(2, 6, 23, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    outline: none;
}
QTreeWidget::item { padding: 3px 6px; color: #e2e8f0; }
QTreeWidget::item:selected { background: rgba(59, 130, 246, 0.15); }
QTreeWidget::item:hover:!selected { background: transparent; }
/* ─ Headers ─ */
QHeaderView { background: rgba(2, 6, 23, 0.80); border: none; }
QHeaderView::section {
    background: rgba(2, 6, 23, 0.80);
    color: rgba(148, 163, 184, 0.90);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding: 10px;
    border: none;
    border-right: 1px solid rgba(255, 255, 255, 0.05);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
QHeaderView::section:last { border-right: none; }
/* ─ Line edit ─ */
QLineEdit {
    background: rgba(2, 6, 23, 0.70);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 6px;
    padding: 7px 12px;
    color: #f8fafc;
    font-size: 13px;
}
QLineEdit:focus {
    border: 1px solid rgba(177, 197, 255, 0.50);
    background: rgba(2, 6, 23, 0.85);
}
QLineEdit:read-only { color: rgba(148, 163, 184, 0.80); }
/* ─ Spin box ─ */
QSpinBox {
    background: rgba(2, 6, 23, 0.70);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 6px;
    padding: 5px 8px;
    color: #f8fafc;
}
QSpinBox:focus { border: 1px solid rgba(177, 197, 255, 0.50); }
QSpinBox::up-button, QSpinBox::down-button {
    background: rgba(255,255,255,0.08); border: none; width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: rgba(177, 197, 255, 0.20);
}
/* ─ Checkbox ─ */
QCheckBox { color: rgba(203, 213, 225, 0.85); spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.20);
    border-radius: 4px;
    background: rgba(2,6,23,0.60);
}
QCheckBox::indicator:checked {
    background: transparent;
    border-color: #3b82f6;
    image: url(__CHECKMARK__);
}
/* ─ Splitter ─ */
QSplitter::handle { background: rgba(255,255,255,0.05); }
QSplitter::handle:hover { background: rgba(177, 197, 255, 0.20); }
/* ─ Tabs ─ */
QTabWidget::pane {
    background: rgba(15, 23, 42, 0.50);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
}
QTabBar { background: rgba(15, 23, 42, 0.65); border-radius: 8px; }
QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 12px 20px;
    color: rgba(148, 163, 184, 0.80);
    font-size: 13px;
    font-weight: 500;
    min-width: 80px;
}
QTabBar::tab:selected {
    color: #b1c5ff;
    border-bottom: 3px solid #b1c5ff;
    background: rgba(177, 197, 255, 0.06);
}
QTabBar::tab:hover:!selected {
    color: #f8fafc;
    background: rgba(255, 255, 255, 0.04);
}
/* ─ Status bar ─ */
QStatusBar {
    background: rgba(2, 6, 23, 0.85);
    border: none;
    color: rgba(148, 163, 184, 0.80);
    font-size: 11px;
    font-weight: 500;
    padding: 4px 16px;
}
/* ─ Plain / rich text ─ */
QPlainTextEdit, QTextEdit {
    background: rgba(2, 6, 23, 0.80);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    color: #e2e8f0;
    selection-background-color: rgba(59, 130, 246, 0.25);
}
/* ─ Labels transparent ─ */
QLabel { background: transparent; color: #f8fafc; }
/* ─ Menus ─ */
QMenu {
    background: rgba(15, 23, 42, 0.96);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
}
QMenu::item { padding: 8px 20px; color: #f8fafc; font-size: 13px; }
QMenu::item:selected { background: rgba(59, 130, 246, 0.20); }
/* ─ Tooltip ─ */
QToolTip {
    background: rgba(15, 23, 42, 0.96);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px;
    color: #f8fafc;
    padding: 6px 10px;
    font-size: 11px;
}
""".replace("__CHECKMARK__", _CHECKMARK_SVG)

# ── State badge inline style ──────────────────────────────────────────────────

def state_badge_style(state: str) -> str:
    """Return an inline ``setStyleSheet`` string for a state label/item."""
    text_color, bg_color = STATE_COLORS.get(
        state.lower(), (M["on_surface_variant"], M["surface_container"])
    )
    return (
        f"color: {text_color}; background-color: {bg_color}; "
        f"border-radius: {SHAPE['small']}px; padding: 2px 8px;"
    )
