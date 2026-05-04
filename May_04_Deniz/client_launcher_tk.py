"""Compatibility wrapper for the Tk client manager.

The implementation lives in ``launcher_ui.client_manager_tk``.
"""

from common.manager_support import apply_dpi_awareness
from launcher_ui.client_manager_tk import *  # noqa: F401,F403


if __name__ == "__main__":
    apply_dpi_awareness()
    app = ClientManager()  # noqa: F405
    app.mainloop()
