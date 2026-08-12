"""DCC-MCP Krita extension registration and operator menu actions."""

from __future__ import annotations

import os
import sys

from krita import Extension, Krita

from .runtime import VERSION, start_bridge, stop_bridge


def _set_clipboard_text(text: str) -> None:
    for binding in ("PyQt5", "PySide2"):
        try:
            module = __import__(binding)
            app = module.QtWidgets.QApplication.instance()
            if app is not None:
                app.clipboard().setText(text)
                return
        except Exception:
            continue
    raise RuntimeError("Unable to access the system clipboard")


def _resolve_instance_id() -> str:
    instance_id = os.environ.get("DCC_MCP_INSTANCE_ID")
    return instance_id if instance_id else "standalone-krita-bridge"


def _copy_instance_id() -> None:
    instance_id = _resolve_instance_id()
    try:
        _set_clipboard_text(instance_id)
        print("DCC MCP: Instance ID copied to clipboard")  # noqa: T201
    except RuntimeError:
        print("DCC MCP Instance ID: %s" % instance_id)  # noqa: T201


def _show_message_box(title: str, text: str) -> None:
    try:
        from PyQt5.QtWidgets import QMessageBox
    except ImportError:
        try:
            from PySide2.QtWidgets import QMessageBox
        except ImportError:
            print("%s\n%s" % (title, text))  # noqa: T201
            return
    window = Krita.instance().activeWindow()
    qwindow = window.qwindow() if window is not None else None
    if qwindow is not None:
        QMessageBox.information(qwindow, title, text)
    else:
        print("%s\n%s" % (title, text))  # noqa: T201


def _show_server_info() -> None:
    app = Krita.instance()
    roots = os.environ.get("DCC_MCP_KRITA_ALLOWED_ROOTS", "not configured")
    lines = [
        "Instance: %s" % _resolve_instance_id(),
        "Krita: %s" % app.version(),
        "Bridge: 127.0.0.1:%s" % os.environ.get("DCC_MCP_KRITA_BRIDGE_PORT", "3848"),
        "Allowed roots: %s" % roots,
        "Adapter: %s" % VERSION,
        "Python: %s" % sys.version.split()[0],
    ]
    _show_message_box("DCC MCP — Server Info", "\n".join(lines))


def _show_about() -> None:
    text = (
        "dcc-mcp-krita v%s\nKrita %s\nPython %s\n\n"
        "Typed, authenticated Krita automation for DCC-MCP.\n"
        "https://github.com/dcc-mcp/dcc-mcp-krita"
        % (VERSION, Krita.instance().version(), sys.version.split()[0])
    )
    _show_message_box("About DCC MCP", text)


class DccMcpKritaExtension(Extension):  # type: ignore[name-defined]  # noqa: F821
    def __init__(self, parent: object) -> None:
        super().__init__(parent)  # type: ignore[call-arg]

    def setup(self) -> None:
        start_bridge()

    def createActions(self, window: object) -> None:  # noqa: N802
        copy_action = window.createAction(
            "dcc_mcp_copy_instance_id", "Copy Instance ID", "tools/scripts"
        )
        copy_action.triggered.connect(_copy_instance_id)
        server_action = window.createAction("dcc_mcp_server_info", "Server Info", "tools/scripts")
        server_action.triggered.connect(_show_server_info)
        about_action = window.createAction("dcc_mcp_about", "About DCC MCP", "tools/scripts")
        about_action.triggered.connect(_show_about)


_application = Krita.instance()
_application.addExtension(DccMcpKritaExtension(_application))

try:
    from PyQt5.QtWidgets import QApplication
except ImportError:
    try:
        from PySide2.QtWidgets import QApplication
    except ImportError:
        QApplication = None  # type: ignore[assignment,misc]
if QApplication is not None and QApplication.instance() is not None:
    QApplication.instance().aboutToQuit.connect(stop_bridge)
