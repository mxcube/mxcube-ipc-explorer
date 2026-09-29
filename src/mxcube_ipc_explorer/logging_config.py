"""File logging - since this is a full-screen TUI, nothing can go to
stdout/stderr while it's running (Textual owns the terminal), so every
outbound IPC request and every exception/error is written here instead.
See app.py's call sites and MXCuBEIPCExplorerApp._handle_exception.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("mxcube_ipc_explorer")


def configure_logging(log_file: str) -> None:
    handler = logging.FileHandler(log_file)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
