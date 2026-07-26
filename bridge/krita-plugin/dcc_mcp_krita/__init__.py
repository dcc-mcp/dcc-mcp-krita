"""DCC MCP Krita — unified menu and JSON-lines bridge server.

This pykrita extension provides:
1. A background JSON-lines bridge server for external MCP communication.
2. Unified menu actions: Copy Instance ID, Server Info, About DCC MCP.

The bridge server runs in a daemon thread so Krita's UI remains responsive.
Menu actions appear under Tools → Scripts (standard Krita extension location).
"""

from __future__ import annotations

import json
import os
import socketserver
import sys
import threading

from krita import Extension, Krita

BRIDGE_PORT: int = int(os.environ.get("DCC_MCP_KRITA_BRIDGE_PORT", "3848"))

_bridge_thread: threading.Thread | None = None
_bridge_server: socketserver.ThreadingTCPServer | None = None


# ── Version (hard-coded to avoid import-time side-effects) ───────────────────

VERSION: str = "0.2.0"

# ── Bridge server ────────────────────────────────────────────────────────────


def _document_info(document):
    """Extract metadata from a Krita Document for the bridge."""
    return {
        "name": document.name(),
        "width": document.width(),
        "height": document.height(),
    }


class _BridgeHandler(socketserver.StreamRequestHandler):
    """Single-request JSON-lines handler for the Krita bridge."""

    def handle(self) -> None:
        try:
            request = json.loads(self.rfile.readline())
        except (json.JSONDecodeError, ValueError):
            return
        method = request.get("method", "")
        app = Krita.instance()
        documents = app.documents()
        if method in {"krita.get_status", "krita.ping"}:
            result = {"ready": True, "krita_version": app.version(), "bridge_port": BRIDGE_PORT}
        elif method in {"krita.list_documents", "krita.list_images"}:
            result = [_document_info(document) for document in documents]
        elif method in {"krita.get_active_document", "krita.get_active_image"}:
            document = app.activeDocument()
            result = _document_info(document) if document else None
        else:
            result = {"error": f"Unsupported Krita bridge method: {method}"}
        self.wfile.write(
            (
                json.dumps(
                    {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
                )
                + "\n"
            ).encode()
        )


def _start_bridge() -> None:
    """Start the TCP bridge server in a background daemon thread.

    Idempotent — if already running, this is a no-op.
    """
    global _bridge_thread, _bridge_server
    if _bridge_thread is not None and _bridge_thread.is_alive():
        return

    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    _bridge_server = _Server(("127.0.0.1", BRIDGE_PORT), _BridgeHandler)
    _bridge_thread = threading.Thread(target=_bridge_server.serve_forever, daemon=True)
    _bridge_thread.start()


def _stop_bridge() -> None:
    """Shut down the bridge server."""
    global _bridge_thread, _bridge_server
    if _bridge_server is not None:
        _bridge_server.shutdown()
        _bridge_server.server_close()
        _bridge_server = None
    _bridge_thread = None


# ── Clipboard helper ─────────────────────────────────────────────────────────


def _set_clipboard_text(text: str) -> None:
    """Set the system clipboard text.

    Tries PyQt5 (Krita's bundled binding) first, then PySide2 as fallback.
    Raises RuntimeError if neither binding is available.
    """
    for binding in ("PyQt5", "PySide2"):
        try:
            mod = __import__(binding)
            app = mod.QtWidgets.QApplication.instance()
            if app is not None:
                app.clipboard().setText(text)
                return
        except Exception:
            continue
    raise RuntimeError("Unable to access system clipboard (no Qt binding available)")


# ── Instance ID resolution ───────────────────────────────────────────────────


def _resolve_instance_id() -> str:
    """Resolve the DCC MCP instance UUID.

    Priority:
    1. ``DCC_MCP_INSTANCE_ID`` environment variable.
    2. Running server's ``instance_id`` attribute.
    Falls back to ``"unknown"``.
    """
    instance_id = os.environ.get("DCC_MCP_INSTANCE_ID")
    if instance_id:
        return instance_id

    try:
        from dcc_mcp_krita.server import _server  # type: ignore[import-not-found]

        if _server is not None and getattr(_server, "is_running", False):
            sid = getattr(_server, "instance_id", None)
            if isinstance(sid, str):
                return sid
    except Exception:
        pass

    return "unknown"


def _server_url() -> str:
    """Return the MCP server URL or a placeholder."""
    try:
        from dcc_mcp_krita.server import _server  # type: ignore[import-not-found]

        if _server is not None and getattr(_server, "is_running", False):
            return getattr(_server, "mcp_url", "N/A")
    except Exception:
        pass
    return "N/A"


# ── Menu actions ─────────────────────────────────────────────────────────────


def _copy_instance_id() -> None:
    """Copy the DCC MCP instance UUID to the system clipboard.

    Falls back to ``print()`` when the clipboard is unavailable (headless).
    """
    instance_id = _resolve_instance_id()
    copied = False
    try:
        _set_clipboard_text(instance_id)
        copied = True
    except RuntimeError:
        pass

    if copied:
        print(f"DCC MCP: Instance ID copied to clipboard: {instance_id}")  # noqa: T201
    else:
        print(f"DCC MCP Instance ID: {instance_id}")  # noqa: T201


def _show_server_info() -> None:
    """Display DCC MCP server status information in a dialog."""
    instance_id = _resolve_instance_id()
    mcp_url = _server_url()

    krita_version = "unknown"
    try:
        krita_version = Krita.instance().version()
    except Exception:
        pass

    core_version = "unknown"
    try:
        from dcc_mcp_core.server_base import _package_version  # type: ignore[import-not-found]

        core_version = _package_version() or "unknown"
    except Exception:
        pass

    gateway_port_str = os.environ.get("DCC_MCP_GATEWAY_PORT", "0")
    try:
        gp = int(gateway_port_str)
    except ValueError:
        gp = 0
    gateway_display = "disabled" if gp <= 0 else str(gp)

    lines = [
        f"Instance UUID: {instance_id}",
        f"DCC: Krita {krita_version}",
        f"PID: {os.getpid()}",
        f"MCP URL: {mcp_url}",
        f"Gateway Port: {gateway_display}",
        f"Core Version: {core_version}",
        f"Adapter Version: {VERSION}",
        f"Python: {sys.version.split()[0]}",
    ]
    _show_message_box("DCC MCP — Server Info", "\n".join(lines))


def _show_about() -> None:
    """Show the About DCC MCP dialog with version information."""
    krita_version = "unknown"
    try:
        krita_version = Krita.instance().version()
    except Exception:
        pass

    text = (
        f"dcc-mcp-krita v{VERSION}\n"
        f"Krita {krita_version}\n"
        f"Python {sys.version.split()[0]}\n\n"
        "DCC MCP — AI-driven DCC automation.\n"
        "https://github.com/dcc-mcp/dcc-mcp-krita"
    )
    _show_message_box("About DCC MCP", text)


def _show_message_box(title: str, text: str) -> None:
    """Show a message box using PyQt5 (Krita's bundled binding)."""
    try:
        from PyQt5.QtWidgets import QMessageBox
    except ImportError:
        try:
            from PySide2.QtWidgets import QMessageBox
        except ImportError:
            print(f"{title}\n{text}")  # noqa: T201
            return

    try:
        window = Krita.instance().activeWindow()
        if window is not None:
            qwin = window.qwindow()
            if qwin is not None:
                QMessageBox.information(qwin, title, text)
                return
    except Exception:
        pass

    print(f"{title}\n{text}")  # noqa: T201


# ── Pykrita Extension ───────────────────────────────────────────────────────


class DccMcpKritaExtension(Extension):  # type: ignore[name-defined]  # noqa: F821
    """Krita pykrita extension for DCC MCP.

    Registers unified menu actions and starts the bridge server on load.
    """

    def __init__(self, parent: object) -> None:  # noqa: D107
        super().__init__(parent)  # type: ignore[call-arg]

    def setup(self) -> None:  # noqa: D102
        _start_bridge()

    def createActions(self, window: object) -> None:  # noqa: D102, N802
        copy_action = window.createAction(
            "dcc_mcp_copy_instance_id", "Copy Instance ID", "tools/scripts"
        )
        copy_action.triggered.connect(_copy_instance_id)

        server_action = window.createAction(
            "dcc_mcp_server_info", "Server Info", "tools/scripts"
        )
        server_action.triggered.connect(_show_server_info)

        about_action = window.createAction(
            "dcc_mcp_about", "About DCC MCP", "tools/scripts"
        )
        about_action.triggered.connect(_show_about)


# Register the extension when Krita loads this module.
Krita.instance().addExtension(DccMcpKritaExtension(Krita.instance()))
