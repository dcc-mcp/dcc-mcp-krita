"""Install the bundled Krita extension with staged replacement and rollback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

_PLUGIN_NAME = "dcc_mcp_krita"


def default_pykrita_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "krita" / "pykrita"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "krita"
        / "pykrita"
    )


def _resolve_source_dir() -> Path:
    candidate = Path(__file__).resolve().parent / "krita_plugin"
    if candidate.is_dir():
        return candidate
    candidate = Path(__file__).resolve().parents[2] / "bridge" / "krita-plugin"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Bundled Krita plug-in directory was not found")


def _validate_source(source: Path) -> None:
    required = (
        source / ("%s.desktop" % _PLUGIN_NAME),
        source / _PLUGIN_NAME / "__init__.py",
        source / _PLUGIN_NAME / "runtime.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Bundled Krita plug-in is incomplete: %s" % ", ".join(missing))


def install(destination: Optional[Path] = None) -> Path:
    """Atomically stage the desktop entry and Python package with rollback."""
    target = (destination or default_pykrita_dir()).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    source = _resolve_source_dir()
    _validate_source(source)
    desktop_name = "%s.desktop" % _PLUGIN_NAME
    desktop_destination = target / desktop_name
    module_destination = target / _PLUGIN_NAME
    suffix = uuid.uuid4().hex
    desktop_backup = target / (".%s.backup-%s" % (desktop_name, suffix))
    module_backup = target / (".%s.backup-%s" % (_PLUGIN_NAME, suffix))

    with tempfile.TemporaryDirectory(prefix=".dcc-mcp-krita-install-", dir=str(target)) as temp:
        staging = Path(temp)
        staged_desktop = staging / desktop_name
        staged_module = staging / _PLUGIN_NAME
        shutil.copy2(source / desktop_name, staged_desktop)
        shutil.copytree(source / _PLUGIN_NAME, staged_module)
        if os.name != "nt":
            for python_file in staged_module.rglob("*.py"):
                python_file.chmod(0o755)

        moved_desktop = False
        moved_module = False
        try:
            if desktop_destination.exists():
                os.replace(str(desktop_destination), str(desktop_backup))
                moved_desktop = True
            if module_destination.exists():
                os.replace(str(module_destination), str(module_backup))
                moved_module = True
            os.replace(str(staged_desktop), str(desktop_destination))
            os.replace(str(staged_module), str(module_destination))
        except BaseException:
            if desktop_destination.exists():
                desktop_destination.unlink()
            if module_destination.exists():
                shutil.rmtree(module_destination)
            if moved_desktop and desktop_backup.exists():
                os.replace(str(desktop_backup), str(desktop_destination))
            if moved_module and module_backup.exists():
                os.replace(str(module_backup), str(module_destination))
            raise
        else:
            if desktop_backup.exists():
                desktop_backup.unlink()
            if module_backup.exists():
                shutil.rmtree(module_backup)
    return target


def doctor(destination: Optional[Path] = None) -> dict[str, object]:
    target = (destination or default_pykrita_dir()).expanduser().resolve()
    module = target / _PLUGIN_NAME
    files = {
        "desktop": (target / ("%s.desktop" % _PLUGIN_NAME)).is_file(),
        "init": (module / "__init__.py").is_file(),
        "runtime": (module / "runtime.py").is_file(),
    }
    roots = [
        str(Path(item).expanduser().resolve())
        for item in os.environ.get("DCC_MCP_KRITA_ALLOWED_ROOTS", "").split(os.pathsep)
        if item.strip()
    ]
    return {
        "ready": all(files.values()),
        "destination": str(target),
        "files": files,
        "allowed_roots": roots,
        "restart_required_after_install": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install or inspect the DCC-MCP Krita plug-in")
    parser.add_argument("--destination", type=Path, help="Override the pykrita directory")
    parser.add_argument("--doctor", action="store_true", help="Print installation status as JSON")
    args = parser.parse_args()
    if args.doctor:
        result = doctor(args.destination)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ready"]:
            raise SystemExit(1)
        return
    target = install(args.destination)
    print("Installed DCC-MCP Krita extension to %s; restart Krita and enable it." % target)


def doctor_main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the DCC-MCP Krita plug-in installation")
    parser.add_argument("--destination", type=Path, help="Override the pykrita directory")
    result = doctor(parser.parse_args().destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ready"]:
        raise SystemExit(1)
