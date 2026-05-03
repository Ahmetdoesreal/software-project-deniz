"""QSS stylesheet strings for the Sovereign Sentinel design system.

All functions return stylesheet strings that can be passed to
``widget.setStyleSheet()`` or ``QApplication.setStyleSheet()``.
"""

from __future__ import annotations

from ui.theme import M, SHAPE, STATE_COLORS

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
    background: {M['surface_container']};
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
    background: {M['surface_container']};
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
    background: {M['primary']};
    border-color: {M['primary']};
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


# ── Button variants ───────────────────────────────────────────────────────────

def btn_filled() -> str:
    """Primary action — forged metallic gradient."""
    return f"""
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {M['primary_container']}, stop:1 {M['on_primary_fixed_variant']});
    color: {M['on_surface']};
    border: none;
    border-radius: {SHAPE['small']}px;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.1px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {M['on_primary_fixed_variant']}, stop:1 {M['primary_container']});
}}
QPushButton:pressed {{ background: {M['primary']}88; }}
QPushButton:disabled {{
    background: {M['surface_container']};
    color: {M['on_surface_variant']}66;
}}
"""


def btn_tonal() -> str:
    """Secondary action — command chip feel."""
    return f"""
QPushButton {{
    background-color: {M['secondary_container']};
    color: {M['on_secondary_container']};
    border: none;
    border-radius: {SHAPE['small']}px;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{ background-color: {M['surface_container_highest']}; }}
QPushButton:pressed {{ background-color: {M['secondary_container']}99; }}
QPushButton:disabled {{
    background: {M['surface_container']};
    color: {M['on_surface_variant']}66;
}}
"""


def btn_outlined() -> str:
    """Low-emphasis action — ghost button."""
    return f"""
QPushButton {{
    background-color: transparent;
    color: {M['primary']};
    border: 1px solid {M['outline_variant']};
    border-radius: {SHAPE['small']}px;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {M['surface_container']};
    border-color: {M['outline']};
}}
QPushButton:pressed {{ background-color: {M['surface_container_high']}; }}
QPushButton:disabled {{
    color: {M['on_surface_variant']}66;
    border-color: {M['outline_variant']}66;
}}
"""


def btn_text() -> str:
    """Tertiary action — pure text, no background."""
    return f"""
QPushButton {{
    background-color: transparent;
    color: {M['primary']};
    border: none;
    border-radius: {SHAPE['small']}px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{ background-color: {M['surface_container']}; }}
QPushButton:pressed {{ background-color: {M['surface_container_high']}; }}
QPushButton:disabled {{ color: {M['on_surface_variant']}66; }}
"""


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
