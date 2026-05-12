"""Sovereign Sentinel design tokens.

Ported from software_ui/SE_DASHBOARD/proctor_dashboard.py.
Single source of truth for all colours, typography, and shape values
used by the May_03 Qt UI layer.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

# ── Colour tokens ────────────────────────────────────────────────────────────
M: dict[str, str] = {
    # Background / Surface
    "background":                   "#0d1320",
    "surface":                      "#0d1320",
    "surface_bright":               "#333947",
    "surface_container_lowest":     "#0a1018",
    "surface_container_low":        "#151c28",
    "surface_container":            "#19202c",
    "surface_container_high":       "#232a37",
    "surface_container_highest":    "#2d3543",
    # On-Surface (text)
    "on_surface":                   "#ffffff",
    "on_surface_variant":           "#e0e0e0",
    "outline":                      "#8e909b",
    "outline_variant":              "#444650",
    # Primary — Command Blue
    "primary":                      "#b1c5ff",
    "on_primary":                   "#052c6e",
    "primary_container":            "#00296b",
    "on_primary_container":         "#b1c5ff",
    "on_primary_fixed_variant":     "#264486",
    # Secondary — Command Chip
    "secondary_container":          "#3c4661",
    "on_secondary_container":       "#abb4d4",
    # Surface variant
    "surface_variant":              "#3c4050",
}

# ── State colours ─────────────────────────────────────────────────────────────
# Each entry: (text_colour, container_background)
STATE_COLORS: dict[str, tuple[str, str]] = {
    "running":             (M["primary"],                  M["primary_container"]),
    "waiting":             (M["on_surface_variant"],       M["surface_container"]),
    "admin_paused":        (M["outline"],                  M["surface_container_high"]),
    "disconnected_paused": (M["outline_variant"],          M["surface_container"]),
    "violation_paused":    (M["primary"],                  M["outline_variant"]),
    "awaiting_submission": (M["on_secondary_container"],   M["secondary_container"]),
    "submitted":           (M["on_primary_fixed_variant"], M["surface_container_low"]),
    "banned":              (M["on_surface"],               M["outline_variant"]),
}

STATE_LABEL: dict[str, str] = {
    "running":             "Running",
    "waiting":             "Waiting",
    "admin_paused":        "Paused",
    "disconnected_paused": "Disconnected",
    "violation_paused":    "Violation",
    "awaiting_submission": "Awaiting File",
    "submitted":           "Submitted ✓",
    "banned":              "Banned",
}

# ── Typography scale ──────────────────────────────────────────────────────────
# (point_size, weight, letter_spacing_px)
TY: dict[str, tuple[int, int, float]] = {
    "display_large":   (42, 400, -0.50),
    "display_medium":  (32, 400, -0.25),
    "headline_large":  (22, 500, -0.02),
    "headline_medium": (18, 500,  0.00),
    "headline_small":  (16, 500,  0.00),
    "title_large":     (14, 500,  0.00),
    "title_medium":    (13, 500,  0.10),
    "title_small":     (12, 500,  0.10),
    "body_large":      (13, 400,  0.00),
    "body_medium":     (12, 400,  0.00),
    "body_small":      (11, 400,  0.10),
    "label_large":     (12, 500,  0.10),
    "label_medium":    (11, 500,  0.50),
    "label_small":     (10, 500,  0.50),
}

# ── Shape scale (border-radius in px) ────────────────────────────────────────
SHAPE: dict[str, int] = {
    "none":        0,
    "extra_small": 2,
    "small":       4,
    "medium":      6,
    "large":       8,
    "extra_large": 12,
    "full":        9999,
}


def apply_typography(widget: QWidget, role: str) -> None:
    """Apply a TY scale entry to *widget*'s font."""
    size, weight, _ = TY.get(role, TY["body_large"])
    font = QFont("Inter")
    font.setPointSize(size)
    try:
        font.setWeight(QFont.Weight(int(weight)))
    except (AttributeError, TypeError, ValueError):
        font.setWeight(int(weight))
    widget.setFont(font)
