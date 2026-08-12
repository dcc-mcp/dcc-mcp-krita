"""Exercise every bundled typed tool against a real Krita host."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Optional

from dcc_mcp_krita.server import KritaMcpServer


def post(url: str, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def call(url: str, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    response = post(url, "tools/call", {"name": name, "arguments": arguments or {}})
    result = response.get("result", {})
    if response.get("error") or result.get("isError"):
        raise RuntimeError(json.dumps(response))
    envelope = result.get("structuredContent")
    if envelope is None:
        envelope = json.loads(result["content"][0]["text"])
    job_id = envelope.get("job_id") if isinstance(envelope, dict) else None
    if not job_id:
        return envelope
    deadline = time.monotonic() + 1_800
    while time.monotonic() < deadline:
        poll = post(
            url,
            "tools/call",
            {
                "name": "jobs_get_status",
                "arguments": {"job_id": job_id, "include_result": True},
            },
        )
        poll_result = poll.get("result", {})
        if poll.get("error") or poll_result.get("isError"):
            raise RuntimeError(json.dumps(poll))
        status = poll_result.get("structuredContent")
        if status is None:
            status = json.loads(poll_result["content"][0]["text"])
        if status.get("status") == "completed":
            return status["result"]
        if status.get("status") in {"failed", "cancelled", "interrupted"}:
            raise RuntimeError(json.dumps(status))
        time.sleep(1)
    raise TimeoutError("MCP job %s did not complete within 1800 seconds" % job_id)


def list_tool_names(url: str) -> set[str]:
    names: set[str] = set()
    cursor: Optional[str] = None
    for _page in range(20):
        response = post(url, "tools/list", {"cursor": cursor} if cursor else None)
        if response.get("error"):
            raise RuntimeError(json.dumps(response))
        result = response.get("result", {})
        names.update(item["name"] for item in result.get("tools", []))
        cursor = result.get("nextCursor")
        if not cursor:
            return names
    raise RuntimeError("MCP tools/list exceeded the 20-page smoke-test budget")


def typed_name(names: set[str], base_name: str) -> str:
    return next(name for name in names if name == base_name or name.endswith("__" + base_name))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            if os.path.commonpath((str(path), str(root))) == str(root):
                return True
        except ValueError:
            continue
    return False


def main() -> None:
    smoke_root_value = os.environ.get("DCC_MCP_KRITA_SMOKE_ROOT")
    if not smoke_root_value:
        raise RuntimeError("DCC_MCP_KRITA_SMOKE_ROOT must name an allowed writable directory")
    smoke_root = Path(smoke_root_value).expanduser().resolve()
    if not smoke_root.is_dir():
        raise RuntimeError("DCC_MCP_KRITA_SMOKE_ROOT must name an existing directory")
    allowed = [
        Path(item).expanduser().resolve()
        for item in os.environ.get("DCC_MCP_KRITA_ALLOWED_ROOTS", "").split(os.pathsep)
        if item.strip()
    ]
    if not inside(smoke_root, allowed):
        raise RuntimeError("Smoke root must be inside DCC_MCP_KRITA_ALLOWED_ROOTS")

    evidence = Path(tempfile.mkdtemp(prefix="dcc-mcp-krita-live-", dir=str(smoke_root)))
    registry = evidence / "registry"
    os.environ["DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS"] = "1"
    server = KritaMcpServer(port=0, registry_dir=str(registry))
    try:
        server.register_builtin_actions()
        server.start(install_atexit_hook=False)
        call(server.mcp_url, "load_skill", {"skill_name": "krita-document-authoring"})
        names = list_tool_names(server.mcp_url)
        base_names = (
            "get_status",
            "list_documents",
            "get_active_document",
            "inspect_document",
            "list_layers",
            "create_document",
            "open_document",
            "save_document",
            "export_document",
            "create_paint_layer",
            "fill_rectangle",
            "set_layer_properties",
            "set_active_layer",
            "delete_layer",
            "flatten_document",
            "close_document",
        )
        tools = {name: typed_name(names, name) for name in base_names}

        status = call(server.mcp_url, tools["get_status"])
        created = call(
            server.mcp_url,
            tools["create_document"],
            {"width": 512, "height": 512, "name": "DCC_MCP_Texture", "resolution": 72},
        )
        document_id = created["context"]["document_id"]
        layers = {}
        for name in ("Background", "Accent", "Foreground"):
            result = call(
                server.mcp_url,
                tools["create_paint_layer"],
                {"document_id": document_id, "name": name},
            )
            layers[name] = result["context"]["node_id"]
        call(
            server.mcp_url,
            tools["fill_rectangle"],
            {
                "document_id": document_id,
                "node_id": layers["Background"],
                "x": 0,
                "y": 0,
                "width": 512,
                "height": 512,
                "color": [13, 28, 52, 255],
            },
        )
        call(
            server.mcp_url,
            tools["fill_rectangle"],
            {
                "document_id": document_id,
                "node_id": layers["Accent"],
                "x": 64,
                "y": 64,
                "width": 384,
                "height": 384,
                "color": [35, 196, 222, 220],
            },
        )
        call(
            server.mcp_url,
            tools["fill_rectangle"],
            {
                "document_id": document_id,
                "node_id": layers["Foreground"],
                "x": 160,
                "y": 160,
                "width": 192,
                "height": 192,
                "color": [157, 100, 255, 255],
            },
        )
        call(
            server.mcp_url,
            tools["set_layer_properties"],
            {"document_id": document_id, "node_id": layers["Accent"], "opacity": 210},
        )
        call(
            server.mcp_url,
            tools["set_active_layer"],
            {"document_id": document_id, "node_id": layers["Foreground"]},
        )
        inspected = call(
            server.mcp_url,
            tools["inspect_document"],
            {"document_id": document_id},
        )
        listed_layers = call(
            server.mcp_url,
            tools["list_layers"],
            {"document_id": document_id},
        )
        listed_documents = call(server.mcp_url, tools["list_documents"])
        active = call(server.mcp_url, tools["get_active_document"])

        kra = evidence / "dcc-mcp-krita-live.kra"
        png = evidence / "dcc-mcp-krita-live.png"
        saved = call(
            server.mcp_url,
            tools["save_document"],
            {"document_id": document_id, "path": str(kra), "timeout_secs": 300},
        )
        exported = call(
            server.mcp_url,
            tools["export_document"],
            {"document_id": document_id, "path": str(png), "compression": 6},
        )
        closed = call(
            server.mcp_url,
            tools["close_document"],
            {"document_id": document_id},
        )
        reopened = call(
            server.mcp_url,
            tools["open_document"],
            {"path": str(png), "timeout_secs": 300},
        )
        reopened_id = reopened["context"]["document_id"]
        disposable = call(
            server.mcp_url,
            tools["create_paint_layer"],
            {"document_id": reopened_id, "name": "DeleteMe"},
        )
        call(
            server.mcp_url,
            tools["delete_layer"],
            {
                "document_id": reopened_id,
                "node_id": disposable["context"]["node_id"],
            },
        )
        call(
            server.mcp_url,
            tools["flatten_document"],
            {"document_id": reopened_id, "confirm": True},
        )
        call(
            server.mcp_url,
            tools["close_document"],
            {"document_id": reopened_id, "discard_changes": True},
        )
    finally:
        server.stop()

    assert status["success"] is True
    assert status["context"]["authenticated"] is True
    assert status["context"]["command_count"] == 16
    assert inspected["context"]["layer_count"] >= 3
    assert set(layers).issubset({item["name"] for item in listed_layers["context"]["layers"]})
    assert len(listed_documents["context"]["documents"]) >= 1
    assert active["context"]["document"]["document_id"] == document_id
    assert saved["context"]["sha256"] == sha256(kra)
    assert exported["context"]["sha256"] == sha256(png)
    assert zipfile.is_zipfile(kra)
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert closed["context"]["closed"] is True
    print(
        json.dumps(
            {
                "krita_version": status["context"]["krita_version"],
                "typed_tools": len(tools),
                "layers": sorted(layers),
                "kra": {"path": str(kra), "bytes": kra.stat().st_size, "sha256": sha256(kra)},
                "png": {"path": str(png), "bytes": png.stat().st_size, "sha256": sha256(png)},
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
