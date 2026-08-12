from pathlib import Path

import dcc_mcp_krita
from dcc_mcp_krita.server import KritaMcpServer


def test_server_is_gui_adapter_and_bundles_document_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS", "1")
    server = KritaMcpServer(port=0, registry_dir=str(tmp_path / "registry"))
    assert server._options.instance_type == "gui"
    skill_file = (
        Path(dcc_mcp_krita.__file__).parent / "skills" / "krita-document-authoring" / "SKILL.md"
    )
    assert skill_file.is_file()
