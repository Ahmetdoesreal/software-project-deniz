"""Tk theme helpers for the bundled May_12 UI package."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from common_ui.theme import M


def _style(parent: tk.Misc | None = None) -> ttk.Style:
    return ttk.Style(parent)


def tk_mono_font(parent: tk.Misc | None = None, size: int = 10) -> tkfont.Font:
    """Return a readable monospace font for logs and technical values."""
    for family in ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"):
        try:
            return tkfont.Font(root=parent, family=family, size=size)
        except tk.TclError:
            continue
    return tkfont.nametofont("TkFixedFont")


def style_text_widget(widget: tk.Text) -> None:
    """Apply the dark May_12 text-area style to a Tk text widget."""
    widget.configure(
        background=M["surface_container_lowest"],
        foreground=M["on_surface"],
        insertbackground=M["primary"],
        selectbackground=M["primary_container"],
        selectforeground=M["on_surface"],
        relief=tk.FLAT,
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=M["outline_variant"],
        highlightcolor=M["outline"],
    )


def apply_tk_theme(root: tk.Misc) -> None:
    """Apply the bundled dark theme to a Tk root or toplevel."""
    try:
        root.configure(background=M["background"])
    except tk.TclError:
        pass

    root.option_add("*Font", "Segoe UI 10")
    root.option_add("*Background", M["background"])
    root.option_add("*Foreground", M["on_surface"])
    root.option_add("*Entry.Background", M["surface_container_low"])
    root.option_add("*Entry.Foreground", M["on_surface"])
    root.option_add("*Text.Background", M["surface_container_lowest"])
    root.option_add("*Text.Foreground", M["on_surface"])

    style = _style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=M["background"], foreground=M["on_surface"])
    style.configure("TFrame", background=M["background"])
    style.configure("TLabel", background=M["background"], foreground=M["on_surface"])
    style.configure(
        "TLabelframe",
        background=M["surface_container"],
        foreground=M["on_surface"],
        bordercolor=M["outline_variant"],
        lightcolor=M["surface_container"],
        darkcolor=M["surface_container"],
    )
    style.configure(
        "TLabelframe.Label",
        background=M["background"],
        foreground=M["on_surface_variant"],
        font=("Segoe UI", 9, "bold"),
    )
    style.configure(
        "TButton",
        background=M["surface_container_high"],
        foreground=M["on_surface"],
        bordercolor=M["outline_variant"],
        focusthickness=1,
        focuscolor=M["outline"],
        padding=(10, 6),
    )
    style.map(
        "TButton",
        background=[
            ("disabled", M["surface_container"]),
            ("pressed", M["primary_container"]),
            ("active", M["surface_container_highest"]),
        ],
        foreground=[
            ("disabled", M["outline"]),
            ("active", M["on_surface"]),
        ],
    )
    style.configure(
        "TEntry",
        fieldbackground=M["surface_container_low"],
        foreground=M["on_surface"],
        bordercolor=M["outline_variant"],
        insertcolor=M["primary"],
    )
    style.configure(
        "TCheckbutton",
        background=M["background"],
        foreground=M["on_surface_variant"],
    )
    style.configure(
        "Treeview",
        background=M["surface_container_low"],
        fieldbackground=M["surface_container_low"],
        foreground=M["on_surface"],
        bordercolor=M["outline_variant"],
        rowheight=24,
    )
    style.configure(
        "Treeview.Heading",
        background=M["surface_container"],
        foreground=M["on_surface_variant"],
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", M["primary_container"])],
        foreground=[("selected", M["on_surface"])],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=M["surface_container_high"],
        troughcolor=M["surface_container_lowest"],
        bordercolor=M["background"],
        arrowcolor=M["on_surface_variant"],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=M["surface_container_high"],
        troughcolor=M["surface_container_lowest"],
        bordercolor=M["background"],
        arrowcolor=M["on_surface_variant"],
    )
