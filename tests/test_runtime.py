"""Host-contract tests for the bundled Krita runtime."""

from __future__ import annotations

import importlib.util
import json
import socket
import socketserver
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

RUNTIME_PATH = (
    Path(__file__).resolve().parents[1] / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "runtime.py"
)


class FakeUuid:
    def __init__(self, value: str) -> None:
        self.value = value

    def toString(self) -> str:  # noqa: N802
        return self.value


class FakeNode:
    _counter = 0

    def __init__(self, name: str, node_type: str = "paintlayer") -> None:
        FakeNode._counter += 1
        self._id = "node-%d" % FakeNode._counter
        self._name = name
        self._type = node_type
        self._visible = True
        self._locked = False
        self._opacity = 255
        self._children: list[FakeNode] = []
        self._parent: FakeNode | None = None
        self.pixel_write: tuple[bytes, int, int, int, int] | None = None

    def uniqueId(self) -> FakeUuid:  # noqa: N802
        return FakeUuid(self._id)

    def name(self) -> str:
        return self._name

    def setName(self, value: str) -> None:  # noqa: N802
        self._name = value

    def type(self) -> str:
        return self._type

    def visible(self) -> bool:
        return self._visible

    def setVisible(self, value: bool) -> None:  # noqa: N802
        self._visible = value

    def locked(self) -> bool:
        return self._locked

    def setLocked(self, value: bool) -> None:  # noqa: N802
        self._locked = value

    def opacity(self) -> int:
        return self._opacity

    def setOpacity(self, value: int) -> None:  # noqa: N802
        self._opacity = value

    def childNodes(self) -> list["FakeNode"]:  # noqa: N802
        return list(self._children)

    def parentNode(self) -> "FakeNode | None":  # noqa: N802
        return self._parent

    def addChildNode(self, node: "FakeNode", _above: Any) -> bool:  # noqa: N802
        node._parent = self
        self._children.append(node)
        return True

    def removeChildNode(self, node: "FakeNode") -> bool:  # noqa: N802
        if node not in self._children:
            return False
        self._children.remove(node)
        node._parent = None
        return True

    def setPixelData(  # noqa: N802
        self, value: bytes, x: int, y: int, width: int, height: int
    ) -> bool:
        self.pixel_write = (bytes(value), x, y, width, height)
        return True


class FakeDocument:
    def __init__(self, width: int, height: int, name: str) -> None:
        self._width = width
        self._height = height
        self._name = name
        self._file_name = ""
        self._modified = False
        self._batchmode = False
        self._closed = False
        self._root = FakeNode("root", "grouplayer")
        self._active: FakeNode | None = None
        self.flattened = False

    def name(self) -> str:
        return self._name

    def fileName(self) -> str:  # noqa: N802
        return self._file_name

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def resolution(self) -> int:
        return 300

    def colorModel(self) -> str:  # noqa: N802
        return "RGBA"

    def colorDepth(self) -> str:  # noqa: N802
        return "U8"

    def colorProfile(self) -> str:  # noqa: N802
        return "sRGB-elle-V2-srgbtrc.icc"

    def modified(self) -> bool:
        return self._modified

    def setModified(self, value: bool) -> None:  # noqa: N802
        self._modified = value

    def batchmode(self) -> bool:
        return self._batchmode

    def setBatchmode(self, value: bool) -> None:  # noqa: N802
        self._batchmode = value

    def rootNode(self) -> FakeNode:  # noqa: N802
        return self._root

    def activeNode(self) -> FakeNode | None:  # noqa: N802
        return self._active

    def setActiveNode(self, node: FakeNode) -> None:  # noqa: N802
        self._active = node

    def createNode(self, name: str, node_type: str) -> FakeNode:  # noqa: N802
        return FakeNode(name, node_type)

    def refreshProjection(self) -> None:  # noqa: N802
        return None

    def saveAs(self, path: str) -> bool:  # noqa: N802
        Path(path).write_bytes(b"fake-kra")
        self._file_name = path
        self._modified = False
        return True

    def exportImage(self, path: str, _options: Any) -> bool:  # noqa: N802
        Path(path).write_bytes(b"fake-png")
        return True

    def flatten(self) -> None:
        self.flattened = True
        self._root._children = [FakeNode("flattened", "paintlayer")]

    def close(self) -> bool:
        self._closed = True
        return True


class FakeWindow:
    def __init__(self) -> None:
        self.views: list[FakeDocument] = []

    def addView(self, document: FakeDocument) -> None:  # noqa: N802
        self.views.append(document)


class FakeApp:
    def __init__(self) -> None:
        self._documents: list[FakeDocument] = []
        self.window = FakeWindow()

    def version(self) -> str:
        return "5.2.11"

    def documents(self) -> list[FakeDocument]:
        return [document for document in self._documents if not document._closed]

    def activeDocument(self) -> FakeDocument | None:  # noqa: N802
        documents = self.documents()
        return documents[-1] if documents else None

    def activeWindow(self) -> FakeWindow:  # noqa: N802
        return self.window

    def createDocument(  # noqa: N802
        self,
        width: int,
        height: int,
        name: str,
        _model: str,
        _depth: str,
        _profile: str,
        _resolution: float,
    ) -> FakeDocument:
        document = FakeDocument(width, height, name)
        self._documents.append(document)
        return document

    def openDocument(self, path: str) -> FakeDocument:  # noqa: N802
        document = FakeDocument(32, 32, Path(path).name)
        document._file_name = path
        self._documents.append(document)
        return document


class FakeInfoObject:
    def __init__(self) -> None:
        self.properties: dict[str, Any] = {}

    def setProperty(self, name: str, value: Any) -> None:  # noqa: N802
        self.properties[name] = value


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("_dcc_mcp_krita_runtime_test", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    app = FakeApp()

    class FakeKrita:
        @staticmethod
        def instance() -> FakeApp:
            return app

    krita_module = types.ModuleType("krita")
    krita_module.Krita = FakeKrita  # type: ignore[attr-defined]
    krita_module.InfoObject = FakeInfoObject  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "krita", krita_module)

    qt_core = types.ModuleType("PyQt5.QtCore")
    qt_core.QByteArray = bytearray  # type: ignore[attr-defined]
    pyqt = types.ModuleType("PyQt5")
    pyqt.QtCore = qt_core  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PyQt5", pyqt)
    monkeypatch.setitem(sys.modules, "PyQt5.QtCore", qt_core)
    monkeypatch.setenv("DCC_MCP_KRITA_ALLOWED_ROOTS", str(tmp_path))
    return module, app


def test_full_document_layer_save_export_and_close(runtime, tmp_path: Path) -> None:
    module, _app = runtime
    created = module._execute_command(
        "krita.create_document", {"width": 16, "height": 8, "name": "Texture"}
    )
    document_id = created["document_id"]
    layer = module._execute_command(
        "krita.create_paint_layer", {"document_id": document_id, "name": "Base Color"}
    )
    node_id = layer["node_id"]

    filled = module._execute_command(
        "krita.fill_rectangle",
        {
            "document_id": document_id,
            "node_id": node_id,
            "x": 2,
            "y": 1,
            "width": 3,
            "height": 2,
            "color": [10, 20, 30, 40],
        },
    )
    assert filled["width"] == 3
    document = _app.documents()[0]
    node = document.activeNode()
    assert node is not None
    assert node.pixel_write == (bytes((30, 20, 10, 40)) * 6, 2, 1, 3, 2)

    changed = module._execute_command(
        "krita.set_layer_properties",
        {"document_id": document_id, "node_id": node_id, "name": "Albedo", "opacity": 200},
    )
    assert changed["changed"] == ["name", "opacity"]
    inspected = module._execute_command("krita.inspect_document", {"document_id": document_id})
    assert inspected["layer_count"] == 1
    assert inspected["layers"][0]["name"] == "Albedo"

    kra = tmp_path / "texture.kra"
    saved = module._execute_command(
        "krita.save_document", {"document_id": document_id, "path": str(kra)}
    )
    assert saved["bytes"] == len(b"fake-kra")
    assert len(saved["sha256"]) == 64
    png = tmp_path / "texture.png"
    exported = module._execute_command(
        "krita.export_document", {"document_id": document_id, "path": str(png)}
    )
    assert exported["bytes"] == len(b"fake-png")
    assert len(exported["sha256"]) == 64
    closed = module._execute_command("krita.close_document", {"document_id": document_id})
    assert closed["closed"] is True


def test_destructive_commands_require_explicit_confirmation(runtime) -> None:
    module, app = runtime
    created = module._execute_command(
        "krita.create_document", {"width": 8, "height": 8, "name": "Unsafe"}
    )
    document_id = created["document_id"]
    document = app.documents()[0]
    document.setModified(True)
    with pytest.raises(module.HostCommandError, match="discard_changes"):
        module._execute_command("krita.close_document", {"document_id": document_id})
    with pytest.raises(module.HostCommandError, match="confirm=true"):
        module._execute_command("krita.flatten_document", {"document_id": document_id})
    flattened = module._execute_command(
        "krita.flatten_document", {"document_id": document_id, "confirm": True}
    )
    assert flattened["flattened"] is True


def test_delete_layer_and_output_root_enforcement(runtime, tmp_path: Path) -> None:
    module, _app = runtime
    created = module._execute_command(
        "krita.create_document", {"width": 8, "height": 8, "name": "Layers"}
    )
    document_id = created["document_id"]
    layer = module._execute_command(
        "krita.create_paint_layer", {"document_id": document_id, "name": "Temporary"}
    )
    deleted = module._execute_command(
        "krita.delete_layer",
        {"document_id": document_id, "node_id": layer["node_id"]},
    )
    assert deleted["deleted"] is True
    with pytest.raises(module.HostCommandError, match="outside"):
        module._execute_command(
            "krita.export_document",
            {"document_id": document_id, "path": str(tmp_path.parent / "outside.png")},
        )


def test_dispatch_executes_on_pump_thread(runtime) -> None:
    module, _app = runtime
    result: dict[str, Any] = {}

    def request() -> None:
        result.update(module._dispatch_to_main_thread("krita.get_status", {}))

    thread = threading.Thread(target=request)
    thread.start()
    deadline = time.monotonic() + 2
    while thread.is_alive() and time.monotonic() < deadline:
        module._drain_commands()
        time.sleep(0.01)
    thread.join(timeout=1)
    assert result["main_thread_id"] == threading.get_ident()
    assert result["command_count"] == 16


def test_bridge_rejects_invalid_token_without_dispatch(runtime) -> None:
    module, _app = runtime
    module._bridge_token = "x" * 32

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(("127.0.0.1", 0), module._BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=2) as connection:
            request = {
                "jsonrpc": "2.0",
                "id": "request-1",
                "token": "wrong" * 8,
                "method": "krita.get_status",
                "params": {},
            }
            connection.sendall((json.dumps(request) + "\n").encode())
            response = json.loads(connection.makefile("r", encoding="utf-8").readline())
        assert response["id"] == "request-1"
        assert response["error"]["message"] == "Bridge authentication failed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
