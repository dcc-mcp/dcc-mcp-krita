"""Authenticated, main-thread Krita bridge runtime."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import secrets
import socketserver
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

VERSION: str = "0.3.0"  # x-release-please-version
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = int(os.environ.get("DCC_MCP_KRITA_BRIDGE_PORT", "3848"))
MAX_REQUEST_BYTES = 1024 * 1024
MAX_QUEUE_DEPTH = 32
MAX_TREE_NODES = 20_000
MAX_FILL_PIXELS = 16_777_216
MAX_DOCUMENT_PIXELS = 100_000_000
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_COMMAND_TIMEOUT_SECS = 1_800.0
OPEN_SUFFIXES = frozenset(
    {".kra", ".ora", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".psd", ".exr"}
)
EXPORT_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"})


class HostCommandError(RuntimeError):
    """A typed request violates the host or safety contract."""


class _PendingCommand:
    def __init__(self, method: str, params: Mapping[str, Any]) -> None:
        self.method = method
        self.params = dict(params)
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[str] = None
        self.cancelled = False


_commands: "queue.Queue[_PendingCommand]" = queue.Queue(maxsize=MAX_QUEUE_DEPTH)
_bridge_thread: Optional[threading.Thread] = None
_bridge_server: Optional[socketserver.ThreadingTCPServer] = None
_command_timer: Any = None
_bridge_token = ""


def _split_roots(value: str) -> tuple[Path, ...]:
    return tuple(
        Path(item.strip()).expanduser().resolve()
        for item in value.split(os.pathsep)
        if item.strip()
    )


def _allowed_roots() -> tuple[Path, ...]:
    return _split_roots(os.environ.get("DCC_MCP_KRITA_ALLOWED_ROOTS", ""))


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    candidate = os.path.normcase(str(path))
    for root in roots:
        normalized_root = os.path.normcase(str(root))
        try:
            if os.path.commonpath((candidate, normalized_root)) == normalized_root:
                return True
        except ValueError:
            continue
    return False


def _safe_text(value: Any, label: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostCommandError("%s must be a non-empty string" % label)
    if len(value) > maximum or any(ord(character) < 32 for character in value):
        raise HostCommandError("%s is invalid or exceeds %d characters" % (label, maximum))
    return value.strip()


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HostCommandError("%s must be an integer" % label)
    if value < minimum or value > maximum:
        raise HostCommandError("%s must be between %d and %d" % (label, minimum, maximum))
    return value


def _bounded_float(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HostCommandError("%s must be a number" % label)
    number = float(value)
    if number < minimum or number > maximum:
        raise HostCommandError("%s must be between %s and %s" % (label, minimum, maximum))
    return number


def _input_path(value: Any) -> Path:
    roots = _allowed_roots()
    if not roots:
        raise HostCommandError("DCC_MCP_KRITA_ALLOWED_ROOTS is required for file access")
    path = Path(_safe_text(value, "path", 2_048)).expanduser().resolve()
    if not _within(path, roots):
        raise HostCommandError("Input path is outside DCC_MCP_KRITA_ALLOWED_ROOTS")
    if path.suffix.lower() not in OPEN_SUFFIXES:
        raise HostCommandError("Input file type is not supported by the adapter")
    if not path.is_file():
        raise HostCommandError("Input file does not exist")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise HostCommandError("Input file exceeds the configured size limit")
    return path


def _output_path(value: Any, suffixes: frozenset[str], overwrite: bool) -> Path:
    roots = _allowed_roots()
    if not roots:
        raise HostCommandError("DCC_MCP_KRITA_ALLOWED_ROOTS is required for file access")
    path = Path(_safe_text(value, "path", 2_048)).expanduser().resolve()
    if not _within(path, roots):
        raise HostCommandError("Output path is outside DCC_MCP_KRITA_ALLOWED_ROOTS")
    if path.suffix.lower() not in suffixes:
        raise HostCommandError("Output file type is not supported by the adapter")
    if not path.parent.is_dir():
        raise HostCommandError("Output parent directory does not exist")
    if path.exists() and not overwrite:
        raise HostCommandError("Output exists; set overwrite=true to replace it")
    if path.exists() and not path.is_file():
        raise HostCommandError("Output path is not a regular file")
    return path


def _token_path() -> Path:
    configured = os.environ.get("DCC_MCP_KRITA_BRIDGE_TOKEN_FILE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home().joinpath(".dcc-mcp", "krita-bridge-token").resolve()


def _load_or_create_token() -> str:
    configured = os.environ.get("DCC_MCP_KRITA_BRIDGE_TOKEN", "")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("DCC_MCP_KRITA_BRIDGE_TOKEN must contain at least 32 characters")
        return configured
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(token)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return token
    except FileExistsError:
        for _attempt in range(10):
            try:
                existing = path.read_text(encoding="utf-8").strip()
            except OSError:
                existing = ""
            if len(existing) >= 32:
                return existing
            time.sleep(0.02)
    raise RuntimeError("Krita bridge token file is missing, unreadable, or invalid")


def _document_id(document: Any) -> str:
    return "doc-%x" % id(document)


def _node_id(node: Any) -> str:
    unique_id = node.uniqueId()
    return str(unique_id.toString() if hasattr(unique_id, "toString") else unique_id)


def _safe_document_path(document: Any) -> tuple[Optional[str], bool]:
    raw = str(document.fileName() or "")
    if not raw:
        return None, False
    path = Path(raw).expanduser().resolve()
    allowed = bool(_allowed_roots()) and _within(path, _allowed_roots())
    return (str(path) if allowed else path.name), allowed


def _document_info(document: Any) -> dict[str, Any]:
    file_name, path_allowed = _safe_document_path(document)
    active_node = document.activeNode()
    return {
        "document_id": _document_id(document),
        "name": str(document.name()),
        "file_name": file_name,
        "file_path_allowed": path_allowed,
        "width": int(document.width()),
        "height": int(document.height()),
        "resolution": int(document.resolution()),
        "color_model": str(document.colorModel()),
        "color_depth": str(document.colorDepth()),
        "color_profile": str(document.colorProfile()),
        "modified": bool(document.modified()),
        "active_node_id": _node_id(active_node) if active_node is not None else None,
    }


def _resolve_document(app: Any, value: Any) -> Any:
    document_id = _safe_text(value, "document_id", 128)
    for document in app.documents():
        if _document_id(document) == document_id:
            return document
    raise HostCommandError("Krita document was not found in this instance")


def _walk_nodes(root: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stack: list[tuple[Any, Optional[str], int]] = [
        (child, None, 0) for child in reversed(root.childNodes())
    ]
    while stack:
        node, parent_id, depth = stack.pop()
        if len(result) >= MAX_TREE_NODES:
            raise HostCommandError("Layer tree exceeds the configured node limit")
        node_id = _node_id(node)
        children = list(node.childNodes())
        result.append(
            {
                "node_id": node_id,
                "parent_id": parent_id,
                "depth": depth,
                "name": str(node.name()),
                "type": str(node.type()),
                "visible": bool(node.visible()),
                "locked": bool(node.locked()),
                "opacity": int(node.opacity()),
                "child_count": len(children),
            }
        )
        stack.extend((child, node_id, depth + 1) for child in reversed(children))
    return result


def _resolve_node(document: Any, value: Any) -> Any:
    wanted = _safe_text(value, "node_id", 128)
    stack = list(document.rootNode().childNodes())
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > MAX_TREE_NODES:
            break
        if _node_id(node) == wanted:
            return node
        stack.extend(node.childNodes())
    raise HostCommandError("Krita layer was not found in this document")


def _add_view(app: Any, document: Any) -> None:
    window = app.activeWindow()
    if window is not None:
        window.addView(document)


def _file_digest(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _execute_command(method: str, params: Mapping[str, Any]) -> Any:
    from krita import InfoObject, Krita

    app = Krita.instance()
    if method in {"krita.get_status", "krita.ping"}:
        return {
            "ready": True,
            "krita_version": str(app.version()),
            "adapter_version": VERSION,
            "bridge_host": BRIDGE_HOST,
            "bridge_port": BRIDGE_PORT,
            "authenticated": True,
            "main_thread_id": threading.get_ident(),
            "allowed_roots": [str(root) for root in _allowed_roots()],
            "command_count": 16,
            "arbitrary_script_input": False,
        }
    if method in {"krita.list_documents", "krita.list_images"}:
        return [_document_info(document) for document in app.documents()]
    if method in {"krita.get_active_document", "krita.get_active_image"}:
        document = app.activeDocument()
        return _document_info(document) if document is not None else None
    if method == "krita.create_document":
        width = _bounded_int(params.get("width"), "width", 1, 16_384)
        height = _bounded_int(params.get("height"), "height", 1, 16_384)
        if width * height > MAX_DOCUMENT_PIXELS:
            raise HostCommandError("Document exceeds the configured pixel limit")
        name = _safe_text(params.get("name", "Untitled"), "name", 256)
        resolution = _bounded_float(params.get("resolution", 300.0), "resolution", 1, 2_400)
        document = app.createDocument(width, height, name, "RGBA", "U8", "", resolution)
        if document is None:
            raise HostCommandError("Krita failed to create the document")
        _add_view(app, document)
        return _document_info(document)
    if method == "krita.open_document":
        path = _input_path(params.get("path"))
        document = app.openDocument(str(path))
        if document is None:
            raise HostCommandError("Krita failed to open the document")
        _add_view(app, document)
        return _document_info(document)

    document = _resolve_document(app, params.get("document_id"))
    if method in {"krita.inspect_document", "krita.list_layers"}:
        layers = _walk_nodes(document.rootNode())
        result = {**_document_info(document), "layer_count": len(layers), "layers": layers}
        return result if method == "krita.inspect_document" else layers
    if method == "krita.save_document":
        overwrite = bool(params.get("overwrite", False))
        path_value = params.get("path")
        if path_value is None:
            current, allowed = _safe_document_path(document)
            if not current or not allowed:
                raise HostCommandError("A .kra path under an allowed root is required")
            path = _output_path(current, frozenset({".kra"}), True)
        else:
            path = _output_path(path_value, frozenset({".kra"}), overwrite)
        if not document.saveAs(str(path)):
            raise HostCommandError("Krita failed to save the document")
        return _file_digest(path)
    if method == "krita.export_document":
        overwrite = bool(params.get("overwrite", False))
        path = _output_path(params.get("path"), EXPORT_SUFFIXES, overwrite)
        options = InfoObject()
        suffix = path.suffix.lower()
        if suffix == ".png":
            options.setProperty(
                "compression",
                _bounded_int(params.get("compression", 6), "compression", 1, 9),
            )
            options.setProperty("alpha", bool(params.get("alpha", True)))
            options.setProperty("forceSRGB", bool(params.get("force_srgb", True)))
        elif suffix in {".jpg", ".jpeg"}:
            options.setProperty(
                "quality", _bounded_int(params.get("quality", 90), "quality", 0, 100)
            )
            options.setProperty("forceSRGB", bool(params.get("force_srgb", True)))
        old_batchmode = bool(document.batchmode())
        document.setBatchmode(True)
        try:
            if not document.exportImage(str(path), options):
                raise HostCommandError("Krita failed to export the document")
        finally:
            document.setBatchmode(old_batchmode)
        if not path.is_file() or path.stat().st_size <= 0:
            raise HostCommandError("Krita reported success but produced no export artifact")
        return _file_digest(path)
    if method == "krita.create_paint_layer":
        name = _safe_text(params.get("name"), "name", 256)
        parent = document.rootNode()
        parent_id = params.get("parent_id")
        if parent_id is not None:
            parent = _resolve_node(document, parent_id)
            if str(parent.type()).lower() != "grouplayer":
                raise HostCommandError("parent_id must reference a group layer")
        node = document.createNode(name, "paintlayer")
        if node is None or not parent.addChildNode(node, None):
            raise HostCommandError("Krita failed to create the paint layer")
        document.setActiveNode(node)
        return next(
            item for item in _walk_nodes(document.rootNode()) if item["node_id"] == _node_id(node)
        )
    if method == "krita.fill_rectangle":
        node = _resolve_node(document, params.get("node_id"))
        if str(node.type()).lower() != "paintlayer":
            raise HostCommandError("fill_rectangle requires a paint layer")
        if (
            str(document.colorModel()).upper() != "RGBA"
            or str(document.colorDepth()).upper() != "U8"
        ):
            raise HostCommandError("fill_rectangle requires an RGBA/U8 document")
        x = _bounded_int(params.get("x"), "x", 0, int(document.width()) - 1)
        y = _bounded_int(params.get("y"), "y", 0, int(document.height()) - 1)
        width = _bounded_int(params.get("width"), "width", 1, int(document.width()) - x)
        height = _bounded_int(params.get("height"), "height", 1, int(document.height()) - y)
        if width * height > MAX_FILL_PIXELS:
            raise HostCommandError("Rectangle exceeds the configured pixel limit")
        color = params.get("color")
        if not isinstance(color, list) or len(color) not in {3, 4}:
            raise HostCommandError("color must be [red, green, blue] or [red, green, blue, alpha]")
        channels = [_bounded_int(value, "color channel", 0, 255) for value in color]
        if len(channels) == 3:
            channels.append(255)
        red, green, blue, alpha = channels
        data = bytes((blue, green, red, alpha)) * (width * height)
        try:
            from PyQt5.QtCore import QByteArray
        except ImportError:
            from PySide2.QtCore import QByteArray
        if not node.setPixelData(QByteArray(data), x, y, width, height):
            raise HostCommandError("Krita failed to write paint-layer pixels")
        document.setModified(True)
        document.refreshProjection()
        return {"node_id": _node_id(node), "x": x, "y": y, "width": width, "height": height}
    if method == "krita.set_layer_properties":
        node = _resolve_node(document, params.get("node_id"))
        changed = []
        if "name" in params:
            node.setName(_safe_text(params["name"], "name", 256))
            changed.append("name")
        if "visible" in params:
            node.setVisible(bool(params["visible"]))
            changed.append("visible")
        if "locked" in params:
            node.setLocked(bool(params["locked"]))
            changed.append("locked")
        if "opacity" in params:
            node.setOpacity(_bounded_int(params["opacity"], "opacity", 0, 255))
            changed.append("opacity")
        if not changed:
            raise HostCommandError("At least one layer property must be provided")
        document.setModified(True)
        document.refreshProjection()
        return {"node_id": _node_id(node), "changed": changed}
    if method == "krita.set_active_layer":
        node = _resolve_node(document, params.get("node_id"))
        document.setActiveNode(node)
        return {"node_id": _node_id(node), "active": True}
    if method == "krita.delete_layer":
        node = _resolve_node(document, params.get("node_id"))
        parent = node.parentNode()
        if parent is None or not parent.removeChildNode(node):
            raise HostCommandError("Krita failed to delete the layer")
        document.setModified(True)
        document.refreshProjection()
        return {"node_id": _node_id(node), "deleted": True}
    if method == "krita.flatten_document":
        if params.get("confirm") is not True:
            raise HostCommandError("flatten_document requires confirm=true")
        document.flatten()
        document.setModified(True)
        document.refreshProjection()
        return {**_document_info(document), "flattened": True}
    if method == "krita.close_document":
        modified = bool(document.modified())
        if modified and params.get("discard_changes") is not True:
            raise HostCommandError(
                "Document has unsaved changes; set discard_changes=true to close"
            )
        document_id = _document_id(document)
        if not document.close():
            raise HostCommandError("Krita failed to close the document")
        return {"document_id": document_id, "closed": True, "discarded_changes": modified}
    raise HostCommandError("Unsupported Krita bridge method")


def _command_timeout(params: Mapping[str, Any]) -> float:
    raw = params.get("timeout_secs", 120.0)
    return _bounded_float(raw, "timeout_secs", 1.0, MAX_COMMAND_TIMEOUT_SECS)


def _dispatch_to_main_thread(method: str, params: Mapping[str, Any]) -> Any:
    pending = _PendingCommand(method, params)
    try:
        _commands.put_nowait(pending)
    except queue.Full as exc:
        raise HostCommandError("Krita main-thread command queue is full") from exc
    if not pending.event.wait(_command_timeout(params)):
        pending.cancelled = True
        raise HostCommandError("Krita main-thread command timed out")
    if pending.error:
        raise HostCommandError(pending.error)
    return pending.result


def _drain_commands() -> None:
    for _item in range(8):
        try:
            pending = _commands.get_nowait()
        except queue.Empty:
            return
        if pending.cancelled:
            pending.event.set()
            continue
        try:
            pending.result = _execute_command(pending.method, pending.params)
        except HostCommandError as exc:
            pending.error = str(exc)
        except Exception as exc:
            pending.error = "Krita host command failed: %s" % type(exc).__name__
        finally:
            pending.event.set()


class _BridgeHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(10)
        request_id: Any = None
        try:
            raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                raise HostCommandError("Bridge request is empty, incomplete, or oversized")
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, Mapping):
                raise HostCommandError("Bridge request must be a JSON object")
            request_id = request.get("id")
            if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
                raise HostCommandError("Bridge request id must be a string or integer")
            token = request.get("token", "")
            if not isinstance(token, str) or not hmac.compare_digest(token, _bridge_token):
                raise HostCommandError("Bridge authentication failed")
            method = _safe_text(request.get("method"), "method", 128)
            params = request.get("params", {})
            if not isinstance(params, Mapping):
                raise HostCommandError("Bridge params must be an object")
            result = _dispatch_to_main_thread(method, params)
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (HostCommandError, UnicodeError, json.JSONDecodeError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": "bridge_error", "message": str(exc)},
            }
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": "internal_error",
                    "message": "Bridge request failed: %s" % type(exc).__name__,
                },
            }
        self.wfile.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))


def _start_command_timer() -> None:
    global _command_timer
    if _command_timer is not None:
        return
    try:
        from PyQt5.QtCore import QTimer
    except ImportError:
        from PySide2.QtCore import QTimer
    _command_timer = QTimer()
    _command_timer.setInterval(10)
    _command_timer.timeout.connect(_drain_commands)
    _command_timer.start()


def start_bridge() -> None:
    """Start the authenticated bridge and UI-thread queue exactly once."""
    global _bridge_server, _bridge_thread, _bridge_token
    if _bridge_thread is not None and _bridge_thread.is_alive():
        return
    _bridge_token = _load_or_create_token()
    _start_command_timer()

    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
        request_queue_size = 16

    _bridge_server = _Server((BRIDGE_HOST, BRIDGE_PORT), _BridgeHandler)
    _bridge_thread = threading.Thread(
        target=_bridge_server.serve_forever,
        name="dcc-mcp-krita-bridge",
        daemon=True,
    )
    _bridge_thread.start()


def stop_bridge() -> None:
    """Stop bridge resources without touching the Krita application."""
    global _bridge_server, _bridge_thread, _command_timer
    if _bridge_server is not None:
        _bridge_server.shutdown()
        _bridge_server.server_close()
        _bridge_server = None
    if _bridge_thread is not None:
        _bridge_thread.join(timeout=1)
        _bridge_thread = None
    if _command_timer is not None:
        _command_timer.stop()
        _command_timer = None
