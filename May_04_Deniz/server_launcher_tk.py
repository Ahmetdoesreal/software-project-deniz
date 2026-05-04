"""Compatibility wrapper for the Tk server manager.

The implementation lives in ``launcher_ui.server_manager_tk``.
"""

from common.manager_support import apply_dpi_awareness
from launcher_ui.server_manager_tk import *  # noqa: F401,F403


if __name__ == "__main__":
    apply_dpi_awareness()
    app = ServerManager()  # noqa: F405
    app.mainloop()
