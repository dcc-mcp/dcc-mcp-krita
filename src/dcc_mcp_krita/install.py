"""Install the bundled Krita extension with staged replacement and rollback."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Mapping, Optional

from .__version__ import __version__

_PLUGIN_NAME = "dcc_mcp_krita"
_ADAPTER_VERSION = __version__
_SCHEMA_VERSION = "1.0"
_MINIMUM_KRITA = (5, 2)
_MINIMUM_PYTHON = (3, 9)
_MINIMUM_CORE = (0, 19, 38)
_RECEIPT_RELATIVE = Path(".dcc-mcp/receipts/krita.json")
_PYTHON_PROBE = """
import json
import sys
from importlib.metadata import PackageNotFoundError, version

try:
    core_version = version("dcc-mcp-core")
except PackageNotFoundError:
    core_version = None
try:
    import dcc_mcp_krita  # noqa: F401
    adapter_version = version("dcc-mcp-krita")
except (ImportError, PackageNotFoundError):
    adapter_version = None
print(json.dumps({
    "python": ".".join(str(value) for value in sys.version_info[:3]),
    "core": core_version,
    "adapter": adapter_version,
}, separators=(",", ":")))
"""

EXIT_OK = 0
EXIT_PREFLIGHT = 10
EXIT_ACQUIRE = 20
EXIT_INSTALL = 30
EXIT_VERIFY = 40
EXIT_REQUIRES_RESTART = 50


@dataclass(frozen=True)
class LifecycleRequest:
    operation: str
    dcc_path: Optional[Path]
    python_path: Path
    destination: Optional[Path] = None
    version: str = _ADAPTER_VERSION
    yes: bool = False
    dry_run: bool = False
    json_output: bool = False
    repair: bool = False

    def with_operation(self, operation: str) -> "LifecycleRequest":
        return replace(self, operation=operation)


class LifecycleFailure(RuntimeError):
    def __init__(self, exit_code: int, stage: str, reason: str) -> None:
        super().__init__(reason)
        self.exit_code = exit_code
        self.stage = stage
        self.reason = reason


def default_pykrita_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Krita" / "pykrita"
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


def _core_safe_replace_tree(source: Path, destination: Path) -> None:
    """Stage a tree through Core's lock-aware lifecycle primitive."""
    try:
        from dcc_mcp_core.install_lifecycle import safe_replace_tree
    except ImportError:
        shutil.copytree(source, destination)
        return
    result = safe_replace_tree(source, destination)
    if not isinstance(result, Mapping) or not result.get("success"):
        if isinstance(result, Mapping) and (
            result.get("requires_restart") or result.get("status") == "requires_restart"
        ):
            raise LifecycleFailure(
                EXIT_REQUIRES_RESTART,
                "locked_files",
                str(
                    result.get("message") or "Krita plug-in files are loaded; close Krita and retry"
                ),
            )
        reason = "Core could not stage the Krita plug-in tree"
        if isinstance(result, Mapping) and result.get("message"):
            reason = str(result["message"])
        raise OSError(reason)


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
        _core_safe_replace_tree(source / _PLUGIN_NAME, staged_module)
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
        "directly_usable": False,
        "destination": str(target),
        "files": files,
        "receipt_present": _receipt_path(target).is_file(),
        "plugin_enabled": _plugin_enabled(_kritarc_path()),
        "bootstrap_error_log_present": _bootstrap_error_path().is_file(),
        "allowed_roots": roots,
        "restart_required_after_install": True,
    }


def _parse_version(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", value)
    if match is None:
        return ()
    return tuple(int(part) for part in match.groups(default="0"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_path(destination: Path) -> Path:
    return _safe_receipt_path(destination, _RECEIPT_RELATIVE.as_posix(), "receipt")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(data)
        os.replace(str(temporary), str(path))
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _safe_restore_receipt(destination: Path, prior_receipt: Optional[bytes]) -> None:
    """Restore a receipt without allowing a replaced container to escape root."""
    try:
        path = _receipt_path(destination)
        if prior_receipt is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_write(path, prior_receipt)
    except (LifecycleFailure, OSError):
        # The original lifecycle failure remains the source of truth.  Never
        # turn recovery of an unsafe receipt container into an uncaught error.
        return


def _read_receipt(destination: Path) -> Optional[dict[str, Any]]:
    path = _receipt_path(destination)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "receipt", "Krita install receipt is unreadable"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != _SCHEMA_VERSION:
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "receipt", "Krita install receipt schema is unsupported"
        )
    _validate_receipt(destination, value)
    return value


def _safe_receipt_path(destination: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt %s is unsafe" % label)
    # Normalize lexically without resolving symlinks.  Resolving here would
    # turn a receipt path into an operator-owned target before deletion.
    root = Path(os.path.abspath(str(destination)))
    path = Path(os.path.abspath(os.path.join(str(destination), value)))
    try:
        inside = os.path.normcase(os.path.commonpath((str(root), str(path)))) == os.path.normcase(
            str(root)
        )
    except ValueError:
        inside = False
    if not inside:
        raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt %s escapes pykrita" % label)
    _assert_no_reparse_components(root, path, label)
    return path


def _assert_no_reparse_components(root: Path, path: Path, label: str) -> None:
    """Reject symlink/junction components without following them."""
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "receipt", "Receipt %s escapes pykrita" % label
        ) from exc
    current = root
    for component in relative.parts:
        current = current / component
        if not os.path.lexists(str(current)):
            continue
        try:
            attributes = os.lstat(str(current))
        except OSError as exc:
            raise LifecycleFailure(
                EXIT_PREFLIGHT, "receipt", "Receipt %s cannot be inspected" % label
            ) from exc
        if _is_reparse_point(current, attributes):
            raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt %s contains a link" % label)


def _is_reparse_point(path: Path, attributes: Any) -> bool:
    """Detect symlinks and Windows reparse points on Python 3.9+."""
    if stat.S_ISLNK(attributes.st_mode):
        return True
    # Path.is_junction() was added in Python 3.12. Older Windows Python
    # exposes FILE_ATTRIBUTE_REPARSE_POINT through st_file_attributes.
    if int(getattr(attributes, "st_file_attributes", 0)) & 0x0400:
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is None:
        return False
    try:
        return bool(is_junction())
    except (AttributeError, OSError, ValueError):
        return False


def _receipt_file_identity(path: Path, label: str) -> tuple[int, int, int, int]:
    """Return a no-follow identity for an owned regular file."""
    try:
        attributes = os.lstat(str(path))
    except OSError as exc:
        raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt %s changed" % label) from exc
    if _is_reparse_point(path, attributes):
        raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt %s contains a link" % label)
    if not stat.S_ISREG(attributes.st_mode):
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "receipt", "Receipt-owned path is not a regular file"
        )
    return (
        int(attributes.st_dev),
        int(attributes.st_ino),
        int(attributes.st_size),
        int(getattr(attributes, "st_mtime_ns", int(attributes.st_mtime * 1_000_000_000))),
    )


def _receipt_parent_identities(
    root: Path, path: Path, label: str
) -> tuple[tuple[str, tuple[int, int]], ...]:
    """Capture no-follow identities for every directory leading to a receipt file."""
    relative = path.relative_to(root)
    current = root
    identities: list[tuple[str, tuple[int, int]]] = []
    for component in relative.parts[:-1]:
        current = current / component
        try:
            attributes = os.lstat(str(current))
        except OSError as exc:
            raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt %s changed" % label) from exc
        if _is_reparse_point(current, attributes):
            raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt %s contains a link" % label)
        if not stat.S_ISDIR(attributes.st_mode):
            raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt parent is not a directory")
        identities.append(
            (
                component,
                (int(attributes.st_dev), int(attributes.st_ino)),
            )
        )
    return tuple(identities)


class _ReceiptParentHandle:
    """Hold a validated parent directory for no-follow receipt deletion."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: Optional[int] = None
        self.handle: Any = None
        self.physical_path = path
        if os.name == "nt":
            self._open_windows()
        elif os.unlink in getattr(os, "supports_dir_fd", set()):
            self.fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))

    def _open_windows(self) -> None:
        import ctypes
        from ctypes import wintypes

        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.restype = wintypes.HANDLE
        self.handle = create_file(
            str(self.path),
            0x0001,  # FILE_LIST_DIRECTORY
            0x00000001 | 0x00000002 | 0x00000004,  # share read/write/delete
            None,
            3,  # OPEN_EXISTING
            0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
            None,
        )
        if self.handle in (None, wintypes.HANDLE(-1).value):
            raise OSError("Could not open receipt parent directory handle")
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(
            self.handle, buffer, len(buffer), 0
        )
        if not length or length >= len(buffer):
            self.close()
            raise OSError("Could not resolve receipt parent directory handle")
        self.physical_path = Path(buffer.value)

    def identity(self) -> tuple[str, str]:
        if self.fd is not None:
            attributes = os.fstat(self.fd)
            return (str(attributes.st_dev), str(attributes.st_ino))
        if os.name == "nt":
            return (os.path.normcase(str(self.physical_path)), "handle")
        attributes = os.lstat(str(self.path))
        return (str(attributes.st_dev), str(attributes.st_ino))

    def revalidate(self) -> None:
        _assert_no_reparse_components(self.path.parent, self.path, "managed file")
        if os.name == "nt":
            current = _windows_path_key(self.path)
            opened = _windows_path_key(self.physical_path)
            if current != opened:
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt parent changed")
        elif self.fd is not None:
            current = os.lstat(str(self.path))
            opened = os.fstat(self.fd)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt parent changed")

    def unlink(
        self,
        name: str,
        expected_identity: Optional[tuple[int, int, int, int]] = None,
        expected_digest: Optional[str] = None,
    ) -> None:
        # Move the pathname into a private quarantine slot first.  Rename is
        # atomic within the held parent directory, so a replacement that wins
        # the race is what gets sampled below; it can never be deleted through
        # the original operator-visible name.
        quarantine = ".%s.dcc-mcp-unlink-%s" % (name, uuid.uuid4().hex)
        self._rename(name, quarantine)
        keep_quarantine = True
        try:
            actual_identity = self._child_identity(quarantine)
            actual_digest = self._digest(quarantine)
            if (expected_identity is not None and actual_identity != expected_identity) or (
                expected_digest is not None and actual_digest != expected_digest
            ):
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path changed")
            # Re-sample identity after content hashing. This closes the
            # replacement seam between the final digest and quarantine unlink.
            if self._child_identity(quarantine) != actual_identity:
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path changed")
            self._unlink_name(quarantine, actual_identity, actual_digest)
            keep_quarantine = False
        finally:
            if keep_quarantine:
                self._restore_quarantine(quarantine, name)

    def _rename(self, source: str, target: str) -> None:
        if self.fd is not None:
            os.rename(source, target, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        else:
            os.rename(str(self.physical_path / source), str(self.physical_path / target))

    def _unlink_name(
        self,
        name: str,
        expected_identity: Optional[tuple[int, int, int, int]] = None,
        expected_digest: Optional[str] = None,
    ) -> None:
        if expected_identity is not None and self._child_identity(name) != expected_identity:
            raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path changed")
        if expected_digest is not None and self._digest(name) != expected_digest:
            raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path changed")
        if self.fd is not None:
            os.unlink(name, dir_fd=self.fd)
        else:
            os.unlink(str(self.physical_path / name))

    def _restore_quarantine(self, quarantine: str, name: str) -> None:
        """Restore a failed quarantine without overwriting a race winner."""
        try:
            if self.fd is not None:
                os.link(
                    quarantine,
                    name,
                    src_dir_fd=self.fd,
                    dst_dir_fd=self.fd,
                    follow_symlinks=False,
                )
                os.unlink(quarantine, dir_fd=self.fd)
            else:
                os.link(
                    str(self.physical_path / quarantine),
                    str(self.physical_path / name),
                    follow_symlinks=False,
                )
                os.unlink(str(self.physical_path / quarantine))
        except OSError:
            # If the operator has already recreated ``name`` or the platform
            # cannot hard-link this object, leave the quarantine untouched.
            return

    def _digest(self, name: str) -> str:
        """Hash a child opened relative to this validated parent handle."""
        # Windows CRT descriptors default to text mode and normalize CRLF,
        # which would make receipt hashes differ from the bytes on disk.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        if self.fd is not None:
            descriptor = os.open(name, flags, dir_fd=self.fd)
        else:
            descriptor = os.open(str(self.physical_path / name), flags)
        try:
            attributes = os.fstat(descriptor)
            if _is_reparse_point(Path(name), attributes) or not stat.S_ISREG(attributes.st_mode):
                raise LifecycleFailure(
                    EXIT_PREFLIGHT, "receipt", "Receipt-owned path is not a regular file"
                )
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest()
        finally:
            os.close(descriptor)

    def digest(self, name: str) -> str:
        return self._digest(name)

    def _child_identity(self, name: str) -> tuple[int, int, int, int]:
        """Return a no-follow identity for a child under this parent handle."""
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        if self.fd is not None:
            descriptor = os.open(name, flags, dir_fd=self.fd)
        else:
            descriptor = os.open(str(self.physical_path / name), flags)
        try:
            attributes = os.fstat(descriptor)
            if _is_reparse_point(Path(name), attributes) or not stat.S_ISREG(attributes.st_mode):
                raise LifecycleFailure(
                    EXIT_PREFLIGHT, "receipt", "Receipt-owned path is not a regular file"
                )
            return (
                int(attributes.st_dev),
                int(attributes.st_ino),
                int(attributes.st_size),
                int(
                    getattr(
                        attributes,
                        "st_mtime_ns",
                        int(attributes.st_mtime * 1_000_000_000),
                    )
                ),
            )
        finally:
            os.close(descriptor)

    def child_identity(self, name: str) -> tuple[int, int, int, int]:
        return self._child_identity(name)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.handle not in (None, 0):
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "_ReceiptParentHandle":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _windows_path_key(path: Path) -> str:
    """Normalize ordinary and extended-prefix Windows paths for comparison."""
    value = os.path.normcase(os.path.realpath(str(path)))
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return value.rstrip("\\/")


def _validate_receipt(destination: Path, receipt: Mapping[str, Any]) -> None:
    if receipt.get("adapter") != "krita" or receipt.get("version") != _ADAPTER_VERSION:
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "receipt", "Krita install receipt owner is unsupported"
        )
    backup = receipt.get("backup")
    files = receipt.get("managed_files")
    if not isinstance(backup, dict) or not isinstance(files, list):
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "receipt", "Krita install receipt structure is invalid"
        )
    backup_root = _safe_receipt_path(destination, backup.get("root"), "backup root")
    expected_backup_parent = (destination / ".dcc-mcp" / "backups").resolve()
    if backup_root.parent != expected_backup_parent:
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "receipt", "Receipt backup root is outside managed backups"
        )
    if not isinstance(backup.get("desktop"), bool) or not isinstance(backup.get("module"), bool):
        raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt backup flags are invalid")
    if backup["desktop"] and not (backup_root / ("%s.desktop" % _PLUGIN_NAME)).is_file():
        raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt desktop backup is missing")
    if backup["module"] and not (backup_root / _PLUGIN_NAME).is_dir():
        raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt module backup is missing")
    seen: set[str] = set()
    for record in files:
        if not isinstance(record, dict):
            raise LifecycleFailure(
                EXIT_PREFLIGHT, "receipt", "Receipt managed file entry is invalid"
            )
        relative = record.get("path")
        if not isinstance(relative, str) or relative in seen:
            raise LifecycleFailure(
                EXIT_PREFLIGHT, "receipt", "Receipt managed file path is invalid"
            )
        seen.add(relative)
        path = _safe_receipt_path(destination, relative, "managed file")
        allowed = relative == "%s.desktop" % _PLUGIN_NAME or relative.startswith(
            "%s/" % _PLUGIN_NAME
        )
        if not allowed:
            raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt owns an unexpected path")
        if os.path.lexists(str(path)):
            _receipt_file_identity(path, "managed file")
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
            raise LifecycleFailure(
                EXIT_PREFLIGHT, "receipt", "Receipt managed file digest is invalid"
            )


def _managed_files(destination: Path) -> list[dict[str, str]]:
    paths = [destination / ("%s.desktop" % _PLUGIN_NAME)]
    module = destination / _PLUGIN_NAME
    if module.is_dir():
        paths.extend(path for path in sorted(module.rglob("*")) if path.is_file())
    return [
        {"path": path.relative_to(destination).as_posix(), "sha256": _sha256(path)}
        for path in paths
        if path.is_file()
    ]


def _backup_existing(destination: Path) -> dict[str, Any]:
    backup_root = destination / ".dcc-mcp" / "backups" / uuid.uuid4().hex
    desktop = destination / ("%s.desktop" % _PLUGIN_NAME)
    module = destination / _PLUGIN_NAME
    record: dict[str, Any] = {
        "root": backup_root.relative_to(destination).as_posix(),
        "desktop": desktop.is_file(),
        "module": module.is_dir(),
    }
    if record["desktop"]:
        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(desktop, backup_root / desktop.name)
    if record["module"]:
        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(module, backup_root / _PLUGIN_NAME)
    return record


def _remove_plugin_files(destination: Path) -> None:
    (destination / ("%s.desktop" % _PLUGIN_NAME)).unlink(missing_ok=True)
    module = destination / _PLUGIN_NAME
    if module.exists():
        shutil.rmtree(module)


def _remove_receipt_owned_files(destination: Path, managed_files: list[Mapping[str, Any]]) -> None:
    """Remove only paths explicitly owned by a validated install receipt."""
    root = Path(os.path.abspath(str(destination)))
    validated: list[tuple[Path, str, _ReceiptParentHandle]] = []
    parent_handles: dict[Path, _ReceiptParentHandle] = {}
    # Keep every validated parent handle open through the final unlink pass.
    # Reopening by pathname would allow an inter-phase parent swap to redirect
    # deletion into an attacker-controlled directory.
    with ExitStack() as handles:
        # Validate every receipt entry before mutating any of them. This keeps
        # a race on a later entry from causing an earlier entry to be removed.
        for record in managed_files:
            path = _safe_receipt_path(destination, record.get("path"), "managed file")
            if not os.path.lexists(str(path)):
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path is missing")
            parent_handle = parent_handles.get(path.parent)
            if parent_handle is None:
                parent_handle = handles.enter_context(_ReceiptParentHandle(path.parent))
                parent_handles[path.parent] = parent_handle
            parent_before = _receipt_parent_identities(root, path, "managed file")
            before = _receipt_file_identity(path, "managed file")
            # Re-check the no-follow physical identity immediately before
            # unlink; a replacement with a symlink or another inode fails closed.
            parent_after = _receipt_parent_identities(root, path, "managed file")
            after = _receipt_file_identity(path, "managed file")
            parent_handle.revalidate()
            content_digest = parent_handle.digest(path.name)
            content_identity = _receipt_file_identity(path, "managed file")
            parent_handle.revalidate()
            if (
                before != after
                or parent_before != parent_after
                or content_identity != after
                or content_digest != str(record.get("sha256", ""))
            ):
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path changed")
            validated.append((path, str(record.get("sha256", "")), parent_handle))

        # Perform the final no-follow content check and unlink through the same
        # held parent handle used during validation.
        for path, expected_digest, parent_handle in validated:
            parent_handle.revalidate()
            before_identity = parent_handle.child_identity(path.name)
            if parent_handle.digest(path.name) != expected_digest:
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path changed")
            parent_handle.revalidate()
            if parent_handle.child_identity(path.name) != before_identity:
                raise LifecycleFailure(EXIT_PREFLIGHT, "receipt", "Receipt-owned path changed")
            parent_handle.unlink(
                path.name,
                expected_identity=before_identity,
                expected_digest=expected_digest,
            )
    module = destination / _PLUGIN_NAME
    if module.is_dir():
        # Receipt entries own files, not directory containers.  Prune only
        # containers left empty by those removals, preserving operator files.
        for directory in sorted(
            (path for path in module.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            module.rmdir()
        except OSError:
            pass


def _restore_backup(
    destination: Path,
    backup: Mapping[str, Any],
    managed_files: Optional[list[Mapping[str, Any]]] = None,
) -> None:
    if managed_files is None:
        _remove_plugin_files(destination)
    else:
        _remove_receipt_owned_files(destination, managed_files)
    backup_root = destination / str(backup.get("root", ""))
    if backup.get("desktop"):
        shutil.copy2(
            backup_root / ("%s.desktop" % _PLUGIN_NAME),
            destination / ("%s.desktop" % _PLUGIN_NAME),
        )
    if backup.get("module"):
        shutil.copytree(backup_root / _PLUGIN_NAME, destination / _PLUGIN_NAME)


def _remove_backup(destination: Path, backup: Mapping[str, Any]) -> None:
    backup_root = destination / str(backup.get("root", ""))
    if backup_root.is_dir():
        shutil.rmtree(backup_root)


def _resolve_dcc_path(override: Optional[Path]) -> Optional[Path]:
    candidate = override.expanduser() if override is not None else None
    if candidate is None:
        discovered = shutil.which("krita")
        if discovered:
            candidate = Path(discovered)
        elif sys.platform == "darwin":
            candidate = Path("/Applications/krita.app")
        elif os.name == "nt":
            program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            candidates = (
                program_files / "Krita (x64)" / "bin" / "krita.exe",
                program_files / "Krita" / "bin" / "krita.exe",
            )
            candidate = next((path for path in candidates if path.is_file()), None)
        else:
            candidate = Path("/usr/bin/krita")
    if candidate is not None and candidate.suffix.lower() == ".app":
        candidate = candidate / "Contents" / "MacOS" / "krita"
    return candidate.resolve() if candidate is not None and candidate.is_file() else None


def _preflight(request: LifecycleRequest) -> tuple[Path, dict[str, str]]:
    if request.operation not in {"install", "status", "verify", "uninstall", "upgrade"}:
        raise LifecycleFailure(EXIT_PREFLIGHT, "operation", "Unsupported lifecycle operation")
    if request.version != _ADAPTER_VERSION:
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "version", "A fixed installed adapter version is required"
        )
    dcc_path = _resolve_dcc_path(request.dcc_path)
    if dcc_path is None:
        raise LifecycleFailure(
            EXIT_PREFLIGHT,
            "host",
            "Krita was not detected; use --dcc-path to name its executable",
        )
    try:
        completed = subprocess.run(
            [str(dcc_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleFailure(EXIT_PREFLIGHT, "host", "Could not execute Krita --version") from exc
    host_version = _parse_version(completed.stdout if completed.returncode == 0 else "")
    if host_version < _MINIMUM_KRITA:
        raise LifecycleFailure(EXIT_PREFLIGHT, "host", "Krita 5.2+ is required")
    python_path = request.python_path.expanduser().resolve()
    if not python_path.is_file():
        raise LifecycleFailure(EXIT_PREFLIGHT, "python", "--python must name an interpreter")
    try:
        completed = subprocess.run(
            [str(python_path), "-c", _PYTHON_PROBE],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "python", "Could not execute installer Python"
        ) from exc
    probe_output = completed.stdout if completed.returncode == 0 else ""
    try:
        probe = json.loads(probe_output)
    except json.JSONDecodeError:
        probe = None
    if isinstance(probe, dict):
        python_version = _parse_version(str(probe.get("python", "")))
        core_version = probe.get("core")
        adapter_version = probe.get("adapter")
    else:
        python_version = _parse_version(probe_output)
        try:
            core_version = package_version("dcc-mcp-core")
        except PackageNotFoundError:
            core_version = None
        adapter_version = request.version
    if python_version < _MINIMUM_PYTHON:
        raise LifecycleFailure(EXIT_PREFLIGHT, "python", "Installer Python 3.9+ is required")
    if not isinstance(core_version, str):
        raise LifecycleFailure(
            EXIT_PREFLIGHT, "core", "dcc-mcp-core is not installed in the selected Python"
        )
    if _parse_version(core_version) < _MINIMUM_CORE:
        raise LifecycleFailure(EXIT_PREFLIGHT, "core", "dcc-mcp-core 0.19.38+ is required")
    if adapter_version != request.version:
        raise LifecycleFailure(
            EXIT_PREFLIGHT,
            "adapter",
            "The selected Python must import the requested dcc-mcp-krita version",
        )
    destination = (request.destination or default_pykrita_dir()).expanduser().resolve()
    return destination, {
        "adapter_version": request.version,
        "core_version": core_version,
        "krita_version": ".".join(str(part) for part in host_version),
        "dcc_path": str(dcc_path),
        "installer_python": str(python_path),
        "installer_python_version": ".".join(str(part) for part in python_version),
        "host_python": "embedded:krita",
        "destination": str(destination),
    }


def _next_enablement_step() -> dict[str, Any]:
    config_path = _kritarc_path()
    return {
        "id": "enable-krita-plugin",
        "action": "edit_ini",
        "requires_host_closed": True,
        "description": (
            "Enable DCC MCP Krita in Settings > Configure Krita > Python Plugin Manager, "
            "then restart Krita."
        ),
        "file_edit": {
            "path": str(config_path),
            "section": "python",
            "key": "enable_dcc_mcp_krita",
            "value": "true",
        },
        "why": "Krita disables newly discovered Python plug-ins until the operator enables them.",
    }


def _kritarc_path() -> Path:
    configured = os.environ.get("DCC_MCP_KRITA_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "kritarc"
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "kritarc"
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "kritarc"


def _plugin_enabled(config_path: Path) -> bool:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with config_path.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
        return parser.getboolean("python", "enable_dcc_mcp_krita", fallback=False)
    except (OSError, configparser.Error, ValueError):
        return False


def _bootstrap_error_path() -> Path:
    configured = os.environ.get("DCC_MCP_KRITA_BOOTSTRAP_ERRORS")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home().joinpath(".dcc-mcp", "krita-bootstrap-errors.jsonl").resolve()


def _bootstrap_error_since_install(receipt: Mapping[str, Any]) -> Optional[dict[str, str]]:
    path = _bootstrap_error_path()
    if not path.is_file():
        return None
    try:
        installed_at = datetime.fromisoformat(str(receipt.get("installed_at", "")))
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - 64 * 1024))
            lines = stream.read().splitlines()
        for line in reversed(lines):
            value = json.loads(line.decode("utf-8"))
            if not isinstance(value, dict):
                continue
            timestamp = datetime.fromisoformat(str(value.get("timestamp", "")))
            if timestamp < installed_at:
                return None
            return {
                "timestamp": timestamp.isoformat(),
                "stage": str(value.get("stage", "unknown"))[:128],
                "error_type": str(value.get("error_type", "unknown"))[:128],
                "message": str(value.get("message", ""))[:1000],
                "adapter_version": str(value.get("adapter_version", ""))[:128],
            }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return None


def _live_status() -> Mapping[str, Any]:
    from .bridge import KritaBridge

    result = KritaBridge.from_env().call("krita.get_status")
    if not isinstance(result, Mapping):
        raise RuntimeError("Krita bridge returned a non-object status")
    if not result.get("ready") or not result.get("authenticated"):
        raise RuntimeError("Krita bridge is not authenticated and ready")
    if _parse_version(str(result.get("krita_version", ""))) < _MINIMUM_KRITA:
        raise RuntimeError("The live Krita host is older than 5.2")
    if _parse_version(str(result.get("python_version", ""))) < _MINIMUM_PYTHON:
        raise RuntimeError("The live Krita embedded Python is older than 3.9")
    if result.get("adapter_version") != _ADAPTER_VERSION:
        raise RuntimeError("The live Krita plug-in version does not match the installer")
    return result


def _result(
    request: LifecycleRequest,
    *,
    status: str,
    exit_code: int,
    stage: str,
    reason: str,
    destination: Optional[Path] = None,
    detected: Optional[Mapping[str, Any]] = None,
    next_steps: Optional[list[Mapping[str, Any]]] = None,
    directly_usable: bool = False,
) -> dict[str, Any]:
    """Build the thin adapter-local result envelope pending the shared Core facade."""
    if destination is not None:
        try:
            receipt = _receipt_path(destination)
        except (LifecycleFailure, OSError):
            # Keep failure reporting structured even when the receipt
            # container itself is a reparse point or otherwise unsafe.
            receipt = destination / _RECEIPT_RELATIVE
    else:
        receipt = None
    return {
        "schema_version": _SCHEMA_VERSION,
        "operation": request.operation,
        "status": status,
        "exit_code": exit_code,
        "dcc_type": "krita",
        "adapter_version": request.version,
        "core_version": (detected or {}).get("core_version"),
        "steps": [],
        "next_steps": list(next_steps or []),
        "receipt_path": str(receipt) if receipt is not None else None,
        "verify": {
            "directly_usable": directly_usable,
            "failure_stage": None if directly_usable else stage,
            "failure_reason": None if directly_usable else reason,
        },
        "detected": dict(detected or {}),
        "stage": stage,
        "reason": reason,
    }


def _installation_state(destination: Path, receipt: Optional[Mapping[str, Any]]) -> tuple[str, str]:
    desktop = destination / ("%s.desktop" % _PLUGIN_NAME)
    module = destination / _PLUGIN_NAME
    if receipt is None:
        if desktop.exists() or module.exists():
            return "partial", "Krita plug-in files exist without an install receipt"
        return "not_installed", "Krita plug-in is not installed"
    for record in receipt.get("managed_files", []):
        path = destination / str(record.get("path", ""))
        if not path.is_file() or _sha256(path) != record.get("sha256"):
            return "partial", "Receipt-managed Krita plug-in files are missing or changed"
    return "installed", "Krita plug-in files match the install receipt"


def _assert_mutation_unlocked(destination: Path) -> None:
    try:
        from dcc_mcp_core.install_lifecycle import inspect_install_root

        inspection = inspect_install_root(destination)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise LifecycleFailure(
            EXIT_PREFLIGHT,
            "core",
            "dcc-mcp-core could not inspect the Krita install root",
        ) from exc
    if not isinstance(inspection, Mapping):
        raise LifecycleFailure(EXIT_PREFLIGHT, "core", "Core install inspection was invalid")
    if inspection.get("requires_restart"):
        raise LifecycleFailure(
            EXIT_REQUIRES_RESTART,
            "locked_files",
            "Krita plug-in files are loaded; close Krita and retry",
        )


def run_lifecycle(request: LifecycleRequest) -> dict[str, Any]:
    destination: Optional[Path] = None
    detected: dict[str, Any] = {}
    try:
        destination, detected = _preflight(request)
        receipt = _read_receipt(destination)
        state, reason = _installation_state(destination, receipt)
        if request.operation == "status":
            return _result(
                request,
                status=state,
                exit_code=EXIT_OK if state in {"installed", "not_installed"} else EXIT_PREFLIGHT,
                stage="status",
                reason=reason,
                destination=destination,
                detected=detected,
            )
        if request.operation == "verify":
            config_path = _kritarc_path()
            enabled = _plugin_enabled(config_path)
            detected.update({"plugin_enabled": enabled, "kritarc_path": str(config_path)})
            if state != "installed":
                return _result(
                    request,
                    status=state,
                    exit_code=EXIT_VERIFY,
                    stage="installation",
                    reason=reason,
                    destination=destination,
                    detected=detected,
                )
            if not enabled:
                return _result(
                    request,
                    status="installed_not_enabled",
                    exit_code=EXIT_VERIFY,
                    stage="enablement",
                    reason="The Krita Python plug-in is not enabled in kritarc",
                    destination=destination,
                    detected=detected,
                    next_steps=[_next_enablement_step()],
                )
            bootstrap_error = _bootstrap_error_since_install(receipt or {})
            if bootstrap_error is not None:
                detected["bootstrap_error"] = bootstrap_error
                return _result(
                    request,
                    status="installed_not_ready",
                    exit_code=EXIT_VERIFY,
                    stage="bootstrap",
                    reason="Krita recorded a plug-in bootstrap failure after installation",
                    destination=destination,
                    detected=detected,
                    next_steps=[_next_enablement_step()],
                )
            try:
                live_status = _live_status()
            except (OSError, RuntimeError, ValueError) as exc:
                return _result(
                    request,
                    status="installed_not_ready",
                    exit_code=EXIT_VERIFY,
                    stage="host_readiness",
                    reason=str(exc) or "The authenticated Krita bridge is unavailable",
                    destination=destination,
                    detected=detected,
                    next_steps=[_next_enablement_step()],
                )
            detected["live_status"] = dict(live_status)
            return _result(
                request,
                status="ready",
                exit_code=EXIT_OK,
                stage="verify",
                reason="The authenticated Krita bridge is ready",
                destination=destination,
                detected=detected,
                directly_usable=True,
            )
        repairable_partial = request.operation in {"install", "upgrade"} and request.repair
        if state == "partial" and not repairable_partial:
            raise LifecycleFailure(EXIT_PREFLIGHT, "partial_install", reason)
        if request.dry_run:
            return _result(
                request,
                status="planned",
                exit_code=EXIT_OK,
                stage="plan",
                reason="Preflight passed; no files were changed",
                destination=destination,
                detected=detected,
            )
        if not request.yes:
            raise LifecycleFailure(
                EXIT_PREFLIGHT, "confirmation", "Use --yes for mutating lifecycle commands"
            )
        if request.operation == "install" and state == "installed" and not request.repair:
            return _result(
                request,
                status="installed",
                exit_code=EXIT_OK,
                stage="install",
                reason="Krita plug-in already matches the install receipt",
                destination=destination,
                detected=detected,
                next_steps=[_next_enablement_step()],
            )
        _assert_mutation_unlocked(destination)
        if request.operation in {"install", "upgrade"}:
            rollback = _backup_existing(destination)
            backup = dict(receipt.get("backup", {})) if receipt is not None else rollback
            prior_receipt = _receipt_path(destination).read_bytes() if receipt is not None else None
            try:
                install(destination)
                payload = {
                    "schema_version": _SCHEMA_VERSION,
                    "adapter": "krita",
                    "version": request.version,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "detected": detected,
                    "backup": backup,
                    "managed_files": _managed_files(destination),
                }
                _write_json(_receipt_path(destination), payload)
            except BaseException:
                _restore_backup(destination, rollback)
                _remove_backup(destination, rollback)
                _safe_restore_receipt(destination, prior_receipt)
                raise
            if receipt is not None:
                _remove_backup(destination, rollback)
            return _result(
                request,
                status="installed",
                exit_code=EXIT_OK,
                stage="install",
                reason="Krita plug-in files were installed and recorded",
                destination=destination,
                detected=detected,
                next_steps=[_next_enablement_step()],
            )
        if receipt is None:
            return _result(
                request,
                status="not_installed",
                exit_code=EXIT_OK,
                stage="uninstall",
                reason="Krita plug-in is already absent",
                destination=destination,
                detected=detected,
            )
        rollback = _backup_existing(destination)
        receipt_path = _receipt_path(destination)
        prior_receipt = receipt_path.read_bytes()
        receipt_parent = _ReceiptParentHandle(receipt_path.parent)
        try:
            receipt_identity = receipt_parent.child_identity(receipt_path.name)
            receipt_digest = receipt_parent.digest(receipt_path.name)
            _restore_backup(
                destination,
                receipt.get("backup", {}),
                receipt.get("managed_files", []),
            )
            receipt_parent.revalidate()
            receipt_parent.unlink(
                receipt_path.name,
                expected_identity=receipt_identity,
                expected_digest=receipt_digest,
            )
        except BaseException as exc:
            # Receipt validation failures are fail-closed: do not recursively
            # delete the plug-in tree while rolling back, because that could
            # remove an operator-owned replacement discovered in the race.
            if not (isinstance(exc, LifecycleFailure) and exc.stage == "receipt"):
                _restore_backup(destination, rollback)
            _safe_restore_receipt(destination, prior_receipt)
            _remove_backup(destination, rollback)
            raise
        finally:
            receipt_parent.close()
        for obsolete_backup in (rollback, receipt.get("backup", {})):
            try:
                _remove_backup(destination, obsolete_backup)
            except OSError:
                pass
        return _result(
            request,
            status="uninstalled",
            exit_code=EXIT_OK,
            stage="uninstall",
            reason="Receipt-managed Krita plug-in files were removed",
            destination=destination,
            detected=detected,
        )
    except LifecycleFailure as exc:
        return _result(
            request,
            status="failed",
            exit_code=exc.exit_code,
            stage=exc.stage,
            reason=exc.reason,
            destination=destination,
            detected=detected,
        )
    except PermissionError:
        return _result(
            request,
            status="requires_restart",
            exit_code=EXIT_REQUIRES_RESTART,
            stage="locked_files",
            reason="Krita plug-in files are locked; close Krita and retry",
            destination=destination,
            detected=detected,
        )
    except OSError as exc:
        return _result(
            request,
            status="failed",
            exit_code=EXIT_INSTALL,
            stage="filesystem",
            reason=str(exc),
            destination=destination,
            detected=detected,
        )


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
