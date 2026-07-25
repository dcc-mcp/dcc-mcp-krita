"""Install the Krita pykrita extension into the user pykrita directory."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

_PLUGIN_NAME = "dcc_mcp_krita"


def default_pykrita_dir() -> Path:
    """Return the default Krita pykrita directory for the current platform."""
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "krita" / "pykrita"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "krita"
        / "pykrita"
    )


def _resolve_source_dir() -> Path:
    """Find the bridge/krita-plugin directory (dev) or installed wheel location."""
    # Wheel layout: dcc_mcp_krita/krita_plugin/...
    candidate = (
        Path(__file__).resolve().parent / "krita_plugin"
    )
    if candidate.is_dir():
        return candidate

    # Dev layout: ../../bridge/krita-plugin
    candidate = Path(__file__).resolve().parents[2] / "bridge" / "krita-plugin"
    if candidate.is_dir():
        return candidate

    raise FileNotFoundError(
        "Bundled Krita plugin directory not found (tried wheel and dev layouts)"
    )


def install(destination: Path | None = None) -> Path:
    """Install the pykrita extension into the user's Krita pykrita directory.

    Copies:
    - ``dcc_mcp_krita.desktop`` → ``<pykrita>/dcc_mcp_krita.desktop``
    - ``dcc_mcp_krita/`` module → ``<pykrita>/dcc_mcp_krita/``
    """
    target = (destination or default_pykrita_dir()).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    source_dir = _resolve_source_dir()

    # Install .desktop file
    desktop_src = source_dir / f"{_PLUGIN_NAME}.desktop"
    if not desktop_src.is_file():
        raise FileNotFoundError(f"Desktop entry not found: {desktop_src}")
    shutil.copy2(desktop_src, target / desktop_src.name)

    # Install plugin module directory
    module_src = source_dir / _PLUGIN_NAME
    if not module_src.is_dir():
        raise FileNotFoundError(f"Plugin module directory not found: {module_src}")
    module_dst = target / _PLUGIN_NAME
    if module_dst.exists():
        shutil.rmtree(module_dst)
    shutil.copytree(module_src, module_dst)

    if os.name != "nt":
        for py_file in module_dst.rglob("*.py"):
            py_file.chmod(0o755)

    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Install DCC MCP Krita pykrita extension")
    parser.add_argument("--destination", type=Path, help="Override pykrita directory")
    result = install(parser.parse_args().destination)
    print(f"Installed DCC MCP Krita extension to {result}")
