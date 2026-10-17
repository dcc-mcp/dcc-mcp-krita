from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from dcc_mcp_krita.__version__ import __version__ as ADAPTER_VERSION


def test_standard_lifecycle_round_trip_writes_and_consumes_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        version=ADAPTER_VERSION,
        yes=True,
    )

    installed = run_lifecycle(request)
    receipt_path = Path(str(installed["receipt_path"]))
    assert installed["exit_code"] == 0
    assert receipt_path.is_file()

    status = run_lifecycle(request.with_operation("status"))
    uninstalled = run_lifecycle(request.with_operation("uninstall"))

    assert status["status"] == "installed"
    assert uninstalled["exit_code"] == 0
    assert not receipt_path.exists()
    assert not (destination / "dcc_mcp_krita.desktop").exists()
    assert not (destination / "dcc_mcp_krita").exists()


def test_install_dry_run_returns_plan_without_creating_destination(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        dry_run=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 0
    assert result["status"] == "planned"
    assert result["stage"] == "plan"
    assert not destination.exists()


def test_install_is_idempotent_when_receipt_and_hashes_already_match(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    receipt = destination / ".dcc-mcp" / "receipts" / "krita.json"
    original_receipt = receipt.read_bytes()
    monkeypatch.setattr(
        installer,
        "install",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected rewrite")),
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 0
    assert result["status"] == "installed"
    assert receipt.read_bytes() == original_receipt


@pytest.mark.parametrize(
    "with_operator_file", [False, True], ids=["backup-only", "backup-and-operator"]
)
def test_repair_uninstall_restores_preexisting_plugin_files(
    tmp_path: Path, monkeypatch, with_operator_file: bool
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    module = destination / "dcc_mcp_krita"
    module.mkdir(parents=True)
    desktop = destination / "dcc_mcp_krita.desktop"
    desktop.write_text("previous desktop\n", encoding="utf-8")
    previous_init = module / "__init__.py"
    previous_init.write_text("PREVIOUS = True\n", encoding="utf-8")
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        version=ADAPTER_VERSION,
        yes=True,
        repair=True,
    )

    assert run_lifecycle(request)["exit_code"] == 0
    operator_file = module / "operator.txt"
    if with_operator_file:
        operator_file.write_text("operator-owned\n", encoding="utf-8")
    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 0
    assert desktop.read_text(encoding="utf-8") == "previous desktop\n"
    assert previous_init.read_text(encoding="utf-8") == "PREVIOUS = True\n"
    if with_operator_file:
        assert operator_file.read_text(encoding="utf-8") == "operator-owned\n"


@pytest.mark.parametrize(
    "conflict",
    [
        "file",
        "directory",
        "symlink",
        "backup-symlink",
        "publish-race",
        "publish-error",
        "copy-error",
    ],
)
def test_repair_uninstall_preserves_receipt_backup_and_operator_data_on_conflict(
    tmp_path: Path, monkeypatch, conflict: str
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    module = destination / "dcc_mcp_krita"
    module.mkdir(parents=True)
    (destination / "dcc_mcp_krita.desktop").write_text("previous desktop\n", encoding="utf-8")
    (module / "__init__.py").write_text("PREVIOUS = True\n", encoding="utf-8")
    (module / "legacy.txt").write_text("previous legacy\n", encoding="utf-8")
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
        repair=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    receipt = destination / ".dcc-mcp" / "receipts" / "krita.json"
    original_receipt = receipt.read_bytes()
    payload = json.loads(original_receipt)
    backup_root = destination / payload["backup"]["root"]
    managed_bytes = {
        record["path"]: (destination / record["path"]).read_bytes()
        for record in payload["managed_files"]
    }
    operator = module / "legacy.txt"
    note = module / "operator.txt"
    note.write_text("operator-owned\n", encoding="utf-8")
    victim = tmp_path / "operator-victim.txt"
    victim.write_text("untouched victim\n", encoding="utf-8")
    if conflict == "file":
        operator.write_text("operator collision\n", encoding="utf-8")
    elif conflict == "directory":
        operator.mkdir()
        (operator / "keep.txt").write_text("operator collision\n", encoding="utf-8")
    elif conflict in {"symlink", "backup-symlink"}:
        link = operator if conflict == "symlink" else backup_root / "dcc_mcp_krita" / "legacy.txt"
        if conflict == "backup-symlink":
            link.unlink()
        try:
            link.symlink_to(victim)
        except OSError:
            pytest.skip("symlink creation is unavailable on this runner")

    def backup_bytes() -> dict[str, object]:
        return {
            path.relative_to(backup_root).as_posix(): os.readlink(path)
            if path.is_symlink()
            else path.read_bytes()
            for path in backup_root.rglob("*")
            if path.is_symlink() or path.is_file()
        }

    original_backup = backup_bytes()
    publication = "rename" if os.name == "nt" else "link"
    original_publication = getattr(installer.os, publication)
    interrupted = False

    def interrupt_publication(source, target, *args, **kwargs):
        nonlocal interrupted
        if (
            Path(target).name == "legacy.txt"
            and Path(source).parent.name.startswith(".krita-restore-")
            and not interrupted
        ):
            interrupted = True
            if conflict == "publish-race":
                operator.write_text("late operator collision\n", encoding="utf-8")
            elif conflict == "publish-error":
                raise OSError("restore publication interrupted")
        return original_publication(source, target, *args, **kwargs)

    if conflict in {"publish-race", "publish-error"}:
        monkeypatch.setattr(installer.os, publication, interrupt_publication)
    if conflict == "copy-error":
        original_open = Path.open

        def interrupt_copy(target, *args, **kwargs):
            nonlocal interrupted
            if target.parent.name.startswith(".krita-restore-") and not interrupted:
                with original_open(target, "wb") as stream:
                    stream.write(b"partial backup restore")
                interrupted = True
                raise OSError("restore copy interrupted")
            return original_open(target, *args, **kwargs)

        monkeypatch.setattr(Path, "open", interrupt_copy)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == (30 if conflict in {"publish-error", "copy-error"} else 10)
    assert result["stage"] == "receipt"
    assert receipt.read_bytes() == original_receipt
    assert backup_bytes() == original_backup
    assert all(
        (destination / path).read_bytes() == content for path, content in managed_bytes.items()
    )
    assert note.read_text(encoding="utf-8") == "operator-owned\n"
    assert victim.read_text(encoding="utf-8") == "untouched victim\n"
    if conflict == "file":
        assert operator.read_text(encoding="utf-8") == "operator collision\n"
    elif conflict == "directory":
        assert (operator / "keep.txt").read_text(encoding="utf-8") == "operator collision\n"
    elif conflict == "symlink":
        assert operator.is_symlink()
        assert operator.resolve() == victim
    elif conflict == "publish-race":
        assert interrupted
        assert operator.read_text(encoding="utf-8") == "late operator collision\n"
    elif conflict == "publish-error":
        assert interrupted
        assert result["reason"] == "restore publication interrupted"
    elif conflict == "copy-error":
        assert interrupted
        assert result["reason"] == "restore copy interrupted"


@pytest.fixture
def repair_restore_case(tmp_path: Path, monkeypatch):
    import dcc_mcp_krita.install as installer

    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: type("Probe", (), {"returncode": 0, "stdout": "Krita 5.2.11\n"})(),
    )
    destination = tmp_path / "pykrita"
    module = destination / "dcc_mcp_krita"
    module.mkdir(parents=True)
    (destination / "dcc_mcp_krita.desktop").write_bytes(b"previous desktop\n")
    (module / "__init__.py").write_bytes(b"PREVIOUS = True\n")
    (module / "legacy.txt").write_bytes(b"original legacy\n")
    host = tmp_path / "krita.exe"
    host.touch()
    request = installer.LifecycleRequest(
        operation="install",
        dcc_path=host,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
        repair=True,
    )
    assert installer.run_lifecycle(request)["exit_code"] == 0
    receipt = destination / ".dcc-mcp/receipts/krita.json"
    original_receipt = receipt.read_bytes()
    payload = json.loads(original_receipt)
    backup = destination / payload["backup"]["root"]
    managed = {
        record["path"]: (destination / record["path"]).read_bytes()
        for record in payload["managed_files"]
    }
    (module / "operator.txt").write_bytes(b"operator-owned\n")
    return installer, request, module, receipt, original_receipt, backup, managed


def test_backup_restore_cannot_copy_a_swapped_source_inode(
    repair_restore_case, monkeypatch
) -> None:
    installer, request, module, receipt, original_receipt, backup, managed = repair_restore_case
    legacy = backup / "dcc_mcp_krita/legacy.txt"
    original_stat = legacy.stat()
    saved = legacy.with_name("legacy-held.txt")
    original_digest = installer._sha256
    original_copy = installer.shutil.copy2
    original_open = installer.os.open
    swapped = False
    attempted = False

    def swap_source() -> None:
        nonlocal swapped, attempted
        attempted = True
        try:
            legacy.rename(saved)
        except PermissionError:
            # Windows may prevent renaming a held source descriptor outright.
            return
        legacy.write_bytes(b"foreign source\n")
        swapped = True

    def digest_after_swap(path):
        if Path(path) == legacy and not attempted:
            swap_source()
        return original_digest(path)

    def restore_after_copy(source, target, *args, **kwargs):
        value = original_copy(source, target, *args, **kwargs)
        if Path(source) == legacy and swapped:
            legacy.unlink()
            saved.rename(legacy)
        return value

    def swap_after_descriptor_open(path, *args, **kwargs):
        descriptor = original_open(path, *args, **kwargs)
        if not isinstance(path, int) and Path(path) == legacy and not attempted:
            swap_source()
        return descriptor

    monkeypatch.setattr(installer, "_sha256", digest_after_swap)
    monkeypatch.setattr(installer.shutil, "copy2", restore_after_copy)
    monkeypatch.setattr(installer.os, "open", swap_after_descriptor_open)
    try:
        result = installer.run_lifecycle(request.with_operation("uninstall"))
    finally:
        if saved.exists():
            legacy.unlink()
            saved.rename(legacy)

    assert attempted
    assert result["exit_code"] == 0
    assert (module / "legacy.txt").read_bytes() == b"original legacy\n"
    assert (module / "legacy.txt").stat().st_mtime_ns == original_stat.st_mtime_ns
    assert (module / "legacy.txt").stat().st_mode == original_stat.st_mode
    assert (module / "operator.txt").read_bytes() == b"operator-owned\n"
    assert not receipt.exists()


@pytest.mark.parametrize("phase", ["owned-delete", "publication"])
def test_backup_restore_permission_error_preserves_restart_contract(
    repair_restore_case, monkeypatch, phase: str
) -> None:
    installer, request, module, receipt, original_receipt, backup, managed = repair_restore_case
    original_unlink = installer._ReceiptParentHandle.unlink
    publication = "rename" if os.name == "nt" else "link"
    original_publication = getattr(installer.os, publication)

    def locked_delete(parent, name, *args, **kwargs):
        if phase == "owned-delete":
            raise PermissionError("owned file is locked")
        return original_unlink(parent, name, *args, **kwargs)

    def locked_publication(source, target, *args, **kwargs):
        if Path(source).parent.name.startswith(".krita-restore-"):
            raise PermissionError("restore destination is locked")
        return original_publication(source, target, *args, **kwargs)

    monkeypatch.setattr(installer._ReceiptParentHandle, "unlink", locked_delete)
    if phase == "publication":
        monkeypatch.setattr(installer.os, publication, locked_publication)
    result = installer.run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 50
    assert result["status"] == "requires_restart"
    assert result["stage"] == "locked_files"
    assert receipt.read_bytes() == original_receipt
    assert all(
        (request.destination / path).read_bytes() == content for path, content in managed.items()
    )
    assert (module / "operator.txt").read_bytes() == b"operator-owned\n"
    assert (backup / "dcc_mcp_krita/legacy.txt").read_bytes() == b"original legacy\n"


def test_repair_uninstall_preserves_backup_extended_attributes(tmp_path: Path, monkeypatch) -> None:
    if os.name != "posix" or not all(hasattr(os, name) for name in ("setxattr", "getxattr")):
        pytest.skip("POSIX extended attributes are unavailable")
    import errno

    import dcc_mcp_krita.install as installer

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "pykrita"
    module = destination / "dcc_mcp_krita"
    module.mkdir(parents=True)
    legacy = module / "legacy.txt"
    legacy.write_bytes(b"previous file\n")
    attribute = "user.dcc_mcp_krita_restore"
    try:
        os.setxattr(legacy, attribute, b"previous metadata")
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
            pytest.skip("The temporary filesystem does not support extended attributes")
        raise
    host = tmp_path / "krita.exe"
    host.touch()
    request = installer.LifecycleRequest(
        operation="install",
        dcc_path=host,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
        repair=True,
    )
    assert installer.run_lifecycle(request)["exit_code"] == 0
    receipt = destination / ".dcc-mcp/receipts/krita.json"
    backup = destination / json.loads(receipt.read_bytes())["backup"]["root"]
    assert os.getxattr(backup / "dcc_mcp_krita/legacy.txt", attribute) == b"previous metadata"
    (module / "operator.txt").write_bytes(b"operator-owned\n")

    result = installer.run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 0
    assert legacy.read_bytes() == b"previous file\n"
    assert os.getxattr(legacy, attribute) == b"previous metadata"
    assert (module / "operator.txt").read_bytes() == b"operator-owned\n"
    assert not receipt.exists()


@pytest.mark.parametrize("cleanup_failure", ["locked", "replacement"])
def test_backup_restore_attempts_all_cleanup_and_retains_incomplete_recovery(
    repair_restore_case, monkeypatch, cleanup_failure: str
) -> None:
    installer, request, module, receipt, original_receipt, backup, managed = repair_restore_case
    publication = "rename" if os.name == "nt" else "link"
    original_publication = getattr(installer.os, publication)
    original_unlink = installer._ReceiptParentHandle.unlink
    failed = False
    cleanup_attempts = []

    def fail_last_publication(source, target, *args, **kwargs):
        nonlocal failed
        if Path(target).name == "legacy.txt" and Path(source).parent.name.startswith(
            ".krita-restore-"
        ):
            failed = True
            if cleanup_failure == "replacement":
                (module / "__init__.py").unlink()
                (module / "__init__.py").write_bytes(b"operator replacement\n")
            raise OSError("original publication failure")
        return original_publication(source, target, *args, **kwargs)

    def fail_one_cleanup(parent, name, *args, **kwargs):
        if failed:
            cleanup_attempts.append(name)
            if name == "__init__.py" and cleanup_failure == "locked":
                raise PermissionError("published file locked during recovery")
        return original_unlink(parent, name, *args, **kwargs)

    monkeypatch.setattr(installer.os, publication, fail_last_publication)
    monkeypatch.setattr(installer._ReceiptParentHandle, "unlink", fail_one_cleanup)
    result = installer.run_lifecycle(request.with_operation("uninstall"))

    assert "dcc_mcp_krita.desktop" in cleanup_attempts
    assert result["exit_code"] == 30
    assert result["reason"] == "original publication failure"
    assert result["detected"]["recovery_status"] == "incomplete"
    assert result["detected"]["recovery_errors"]
    assert result["detected"]["original_failure"] == {
        "type": "OSError",
        "reason": "original publication failure",
    }
    assert Path(result["detected"]["recovery_backup_root"]).is_dir()
    assert receipt.read_bytes() == original_receipt
    assert (request.destination / "dcc_mcp_krita.desktop").read_bytes() == managed[
        "dcc_mcp_krita.desktop"
    ]
    expected_init = (
        b"operator replacement\n" if cleanup_failure == "replacement" else b"PREVIOUS = True\n"
    )
    assert (module / "__init__.py").read_bytes() == expected_init
    assert (module / "operator.txt").read_bytes() == b"operator-owned\n"
    assert (backup / "dcc_mcp_krita/legacy.txt").read_bytes() == b"original legacy\n"


def test_receipt_failure_rolls_back_repair_to_previous_plugin(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    module = destination / "dcc_mcp_krita"
    module.mkdir(parents=True)
    desktop = destination / "dcc_mcp_krita.desktop"
    desktop.write_text("previous desktop\n", encoding="utf-8")
    previous_init = module / "__init__.py"
    previous_init.write_text("PREVIOUS = True\n", encoding="utf-8")
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    monkeypatch.setattr(
        installer,
        "_write_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("receipt failed")),
    )
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
        repair=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 30
    assert desktop.read_text(encoding="utf-8") == "previous desktop\n"
    assert previous_init.read_text(encoding="utf-8") == "PREVIOUS = True\n"
    assert not (destination / ".dcc-mcp" / "receipts" / "krita.json").exists()


def test_failed_uninstall_rolls_back_to_receipted_plugin(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    module = destination / "dcc_mcp_krita"
    module.mkdir(parents=True)
    (destination / "dcc_mcp_krita.desktop").write_text("previous\n", encoding="utf-8")
    (module / "__init__.py").write_text("PREVIOUS = True\n", encoding="utf-8")
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
        repair=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    installed_init = (module / "__init__.py").read_bytes()
    receipt = destination / ".dcc-mcp" / "receipts" / "krita.json"
    original_restore = installer._restore_backup
    calls = 0

    def fail_after_first_restore(target, backup, managed_files=None):
        nonlocal calls
        calls += 1
        original_restore(target, backup, managed_files)
        if calls == 1:
            raise OSError("restore interrupted")

    monkeypatch.setattr(installer, "_restore_backup", fail_after_first_restore)

    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 30
    assert calls == 2
    assert receipt.is_file()
    assert (module / "__init__.py").read_bytes() == installed_init


def test_failed_upgrade_restores_previous_receipt(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    receipt = destination / ".dcc-mcp" / "receipts" / "krita.json"
    original_receipt = receipt.read_bytes()
    monkeypatch.setattr(
        installer,
        "_write_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("receipt failed")),
    )

    result = run_lifecycle(request.with_operation("upgrade"))

    assert result["exit_code"] == 30
    assert receipt.read_bytes() == original_receipt


def test_uninstall_rejects_receipt_paths_outside_pykrita(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    receipt = destination / ".dcc-mcp" / "receipts" / "krita.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["backup"]["root"] = Path(os.path.relpath(victim, destination)).as_posix()
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert (victim / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_uninstall_rejects_missing_receipt_backup_before_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    receipt = destination / ".dcc-mcp" / "receipts" / "krita.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["backup"]["desktop"] = True
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert (destination / "dcc_mcp_krita.desktop").is_file()


def test_uninstall_returns_structured_failure_for_replaced_receipt_container(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    receipts = destination / ".dcc-mcp" / "receipts"
    saved_receipts = destination / ".dcc-mcp" / "receipts-saved"
    receipts.rename(saved_receipts)
    external = tmp_path / "external-receipts"
    external.mkdir()
    try:
        os.symlink(external, receipts, target_is_directory=True)
    except (OSError, NotImplementedError):
        saved_receipts.rename(receipts)
        pytest.skip("symlink creation is unavailable")

    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert result["status"] == "failed"
    assert not (external / "krita.json").exists()


def test_uninstall_restores_managed_files_when_receipt_delete_fails(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    original_unlink = installer._ReceiptParentHandle.unlink

    def fail_receipt_delete(handle: object, name: str, *args: object, **kwargs: object) -> None:
        if name == "krita.json":
            raise installer.LifecycleFailure(10, "receipt", "simulated receipt race")
        original_unlink(handle, name, *args, **kwargs)

    monkeypatch.setattr(installer._ReceiptParentHandle, "unlink", fail_receipt_delete)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert (destination / "dcc_mcp_krita.desktop").is_file()
    assert (destination / "dcc_mcp_krita" / "runtime.py").is_file()


def test_uninstall_fails_closed_for_unreceipted_partial_install(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    destination.mkdir(parents=True)
    desktop = destination / "dcc_mcp_krita.desktop"
    desktop.write_text("unowned\n", encoding="utf-8")
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="uninstall",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 10
    assert result["stage"] == "partial_install"
    assert desktop.read_text(encoding="utf-8") == "unowned\n"


def test_dry_run_reports_partial_install_without_mutation(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    destination.mkdir(parents=True)
    desktop = destination / "dcc_mcp_krita.desktop"
    desktop.write_text("unowned\n", encoding="utf-8")
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        dry_run=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 10
    assert result["stage"] == "partial_install"
    assert desktop.read_text(encoding="utf-8") == "unowned\n"


def test_install_defers_when_core_reports_loaded_artifacts(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_core.install_lifecycle as core_lifecycle

    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    monkeypatch.setattr(
        core_lifecycle,
        "inspect_install_root",
        lambda _root: {"requires_restart": True, "locked_path": "dcc_mcp_krita/runtime.pyd"},
    )
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 50
    assert result["stage"] == "locked_files"
    assert not (destination / "dcc_mcp_krita.desktop").exists()


def test_verify_requires_enabled_plugin_and_authenticated_live_status(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.bridge as bridge_module
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    class LiveBridge:
        def call(self, method: str):
            assert method == "krita.get_status"
            return {
                "ready": True,
                "authenticated": True,
                "krita_version": "5.2.11",
                "adapter_version": ADAPTER_VERSION,
                "python_version": "3.10.12",
            }

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    monkeypatch.setattr(bridge_module.KritaBridge, "from_env", lambda: LiveBridge())
    config = tmp_path / "kritarc"
    config.write_text("[python]\nenable_dcc_mcp_krita=true\n", encoding="utf-8")
    monkeypatch.setenv("DCC_MCP_KRITA_CONFIG", str(config))
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0

    result = run_lifecycle(request.with_operation("verify"))

    assert result["exit_code"] == 0
    assert result["verify"]["directly_usable"] is True
    assert result["detected"]["plugin_enabled"] is True


def test_verify_reports_bootstrap_error_recorded_after_install(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.bridge as bridge_module
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    class LiveBridge:
        def call(self, _method: str):
            return {
                "ready": True,
                "authenticated": True,
                "krita_version": "5.2.11",
                "adapter_version": ADAPTER_VERSION,
                "python_version": "3.10.12",
            }

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    monkeypatch.setattr(bridge_module.KritaBridge, "from_env", lambda: LiveBridge())
    config = tmp_path / "kritarc"
    config.write_text("[python]\nenable_dcc_mcp_krita=true\n", encoding="utf-8")
    monkeypatch.setenv("DCC_MCP_KRITA_CONFIG", str(config))
    error_log = tmp_path / "bootstrap-errors.jsonl"
    monkeypatch.setenv("DCC_MCP_KRITA_BOOTSTRAP_ERRORS", str(error_log))
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    error_log.write_text(
        json.dumps(
            {
                "timestamp": "9999-01-01T00:00:00+00:00",
                "stage": "start_bridge",
                "error_type": "RuntimeError",
                "message": "bridge startup failed",
                "adapter_version": ADAPTER_VERSION,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_lifecycle(request.with_operation("verify"))

    assert result["exit_code"] == 40
    assert result["stage"] == "bootstrap"
    assert result["detected"]["bootstrap_error"]["stage"] == "start_bridge"


def test_live_status_rejects_unsupported_embedded_python(monkeypatch) -> None:
    import dcc_mcp_krita.bridge as bridge_module
    import dcc_mcp_krita.install as installer

    class LiveBridge:
        def call(self, _method: str):
            return {
                "ready": True,
                "authenticated": True,
                "krita_version": "5.2.11",
                "adapter_version": ADAPTER_VERSION,
                "python_version": "3.8.18",
            }

    monkeypatch.setattr(bridge_module.KritaBridge, "from_env", lambda: LiveBridge())

    with pytest.raises(RuntimeError, match="embedded Python"):
        installer._live_status()


def test_lifecycle_cli_emits_one_json_document_and_stable_exit(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.cli import main

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()

    exit_code = main(
        [
            "status",
            "--dcc-path",
            str(dcc_path),
            "--python",
            sys.executable,
            "--destination",
            str(tmp_path / "krita" / "pykrita"),
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["schema_version"] == "1.0"
    assert result["operation"] == "status"
    assert result["exit_code"] == 0


def test_preflight_rejects_installer_python_below_supported_floor(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def probe(command, **_kwargs):
        return Result("Krita 5.2.11\n" if "--version" in command else "2.7.18\n")

    monkeypatch.setattr(installer.subprocess, "run", probe)
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=tmp_path / "krita" / "pykrita",
        yes=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 10
    assert result["stage"] == "python"


def test_preflight_checks_core_floor_in_selected_python(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def probe(command, **_kwargs):
        if "--version" in command:
            return Result("Krita 5.2.11\n")
        return Result(json.dumps({"python": "3.12.1", "core": None}) + "\n")

    monkeypatch.setattr(installer.subprocess, "run", probe)
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=tmp_path / "krita" / "pykrita",
        yes=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 10
    assert result["stage"] == "core"


def test_preflight_requires_adapter_in_selected_python(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def probe(command, **_kwargs):
        if "--version" in command:
            return Result("Krita 5.2.11\n")
        return Result(json.dumps({"python": "3.12.1", "core": "0.20.8", "adapter": None}) + "\n")

    monkeypatch.setattr(installer.subprocess, "run", probe)
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=tmp_path / "krita" / "pykrita",
        yes=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 10
    assert result["stage"] == "adapter"


def test_preflight_detects_krita_from_path_when_override_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    dcc_path = tmp_path / "bin" / "krita"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    monkeypatch.setattr(installer.shutil, "which", lambda _name: str(dcc_path))
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    request = LifecycleRequest(
        operation="status",
        dcc_path=None,
        python_path=Path(sys.executable),
        destination=tmp_path / "krita" / "pykrita",
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 0
    assert result["detected"]["dcc_path"] == str(dcc_path.resolve())


def test_verify_returns_exact_machine_readable_plugin_enablement_step(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    config = tmp_path / "kritarc"
    monkeypatch.setenv("DCC_MCP_KRITA_CONFIG", str(config))
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0

    result = run_lifecycle(request.with_operation("verify"))

    step = result["next_steps"][0]
    assert step["action"] == "edit_ini"
    assert step["requires_host_closed"] is True
    assert step["file_edit"] == {
        "path": str(config.resolve()),
        "section": "python",
        "key": "enable_dcc_mcp_krita",
        "value": "true",
    }


def test_install_guide_covers_standard_lifecycle_contract() -> None:
    guide = Path(__file__).resolve().parents[1].joinpath("install.md").read_text(encoding="utf-8")

    for operation in ("install", "status", "verify", "uninstall", "upgrade"):
        assert "dcc-mcp-krita %s" % operation in guide
    for exit_code in ("`0`", "`10`", "`20`", "`30`", "`40`", "`50`"):
        assert exit_code in guide
    assert "Krita 5.2+" in guide
    assert "Windows" in guide and "macOS" in guide and "Linux" in guide
    assert "Python Plugin Manager" in guide
    assert "https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-krita/main/install.md" in guide
    for heading in (
        "## Requirements",
        "## Supported versions",
        "## Agent quick path",
        "## Manual path",
        "## Verify",
        "## Upgrade",
        "## Uninstall",
        "## Troubleshooting",
    ):
        assert heading in guide


def test_ci_runs_lifecycle_smoke_on_supported_operating_systems() -> None:
    workflow = (
        Path(__file__).resolve().parents[1].joinpath(".github", "workflows", "ci.yml").read_text()
    )

    assert "windows-latest" in workflow
    assert "macos-latest" in workflow
    assert "Lifecycle round-trip smoke" in workflow


def test_install_uses_core_safe_replace_tree_for_staging(monkeypatch, tmp_path: Path) -> None:
    """The adapter delegates staged tree copies to Core's lock-aware helper."""
    import dcc_mcp_krita.install as installer

    calls: list[tuple[Path, Path]] = []
    real = installer._core_safe_replace_tree

    def wrapped(source: Path, destination: Path) -> None:
        calls.append((source, destination))
        real(source, destination)

    monkeypatch.setattr(installer, "_core_safe_replace_tree", wrapped)
    installer.install(tmp_path)

    assert calls
    assert calls[0][0].name == "dcc_mcp_krita"
    assert calls[0][1].name == "dcc_mcp_krita"


def test_skill_guidance_exposes_lifecycle_entrypoint() -> None:
    skill = (
        Path(__file__).resolve().parents[1]
        / "src/dcc_mcp_krita/skills/krita-document-authoring/SKILL.md"
    )
    text = skill.read_text(encoding="utf-8")
    assert "## Installation lifecycle" in text
    assert "dcc-mcp-krita verify" in text
    assert "dcc-mcp-krita uninstall" in text


def test_uninstall_preserves_unowned_files_inside_plugin_directory(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    operator_file = destination / "dcc_mcp_krita" / "operator.txt"
    operator_file.write_text("operator-owned", encoding="utf-8")

    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 0
    assert operator_file.read_text(encoding="utf-8") == "operator-owned"


def test_core_restart_result_keeps_requires_restart_exit_code(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_core.install_lifecycle as core_lifecycle

    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    monkeypatch.setattr(
        core_lifecycle,
        "safe_replace_tree",
        lambda *_args, **_kwargs: {
            "success": False,
            "status": "requires_restart",
            "requires_restart": True,
            "message": "Krita has the plug-in loaded",
        },
    )
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )

    result = run_lifecycle(request)

    assert result["exit_code"] == 50
    assert result["stage"] == "locked_files"
    assert result["status"] == "failed"


def test_uninstall_rejects_receipt_file_replaced_by_symlink_to_unowned_file(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    runtime = destination / "dcc_mcp_krita" / "runtime.py"
    operator_file = destination / "operator.txt"
    operator_file.write_bytes(runtime.read_bytes())
    runtime.unlink()
    try:
        runtime.symlink_to(operator_file)
    except OSError:
        pytest.skip("symlink creation is unavailable on this runner")

    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert operator_file.exists()


def test_uninstall_fails_closed_when_managed_path_swaps_during_reacquisition(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    runtime = destination / "dcc_mcp_krita" / "runtime.py"
    operator_file = destination / "operator.txt"
    operator_file.write_bytes(runtime.read_bytes())
    original_safe_path = installer._safe_receipt_path
    runtime_calls = 0

    def swap_after_validation(root: Path, value: object, label: str) -> Path:
        nonlocal runtime_calls
        if label == "managed file" and str(value).endswith("runtime.py"):
            runtime_calls += 1
            if runtime_calls == 2:
                runtime.unlink()
                try:
                    runtime.symlink_to(operator_file)
                except OSError:
                    pytest.skip("symlink creation is unavailable on this runner")
        return original_safe_path(root, value, label)

    monkeypatch.setattr(installer, "_safe_receipt_path", swap_after_validation)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert operator_file.exists()


def test_unlink_keeps_validated_parent_handle_when_parent_swaps(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    module = destination / "dcc_mcp_krita"
    outside = tmp_path / "operator"
    outside.mkdir()
    victim = outside / "runtime.py"
    victim.write_bytes((module / "runtime.py").read_bytes())
    original_unlink = installer._ReceiptParentHandle.unlink
    swapped = False

    def swap_parent_after_validation(
        handle: object,
        name: str,
        expected_identity: object = None,
        expected_digest: object = None,
    ) -> None:
        nonlocal swapped
        if name == "runtime.py" and not swapped:
            swapped = True
            renamed = module.with_name("dcc_mcp_krita-renamed")
            module.rename(renamed)
            try:
                if os.name == "nt":
                    import subprocess

                    result = subprocess.run(
                        ["cmd.exe", "/c", "mklink", "/J", str(module), str(outside)],
                        check=False,
                        capture_output=True,
                    )
                    if result.returncode != 0:
                        pytest.skip("junction creation is unavailable on this runner")
                else:
                    module.symlink_to(outside, target_is_directory=True)
            except OSError:
                pytest.skip("parent link creation is unavailable on this runner")
        original_unlink(handle, name, expected_identity, expected_digest)

    monkeypatch.setattr(installer._ReceiptParentHandle, "unlink", swap_parent_after_validation)
    receipt = json.loads(
        (destination / ".dcc-mcp" / "receipts" / "krita.json").read_text(encoding="utf-8")
    )
    try:
        installer._remove_receipt_owned_files(destination, receipt["managed_files"])
    except (OSError, installer.LifecycleFailure):
        pass

    assert swapped
    assert victim.exists()


def test_uninstall_rejects_stable_replacement_after_identity_check(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    runtime = destination / "dcc_mcp_krita" / "runtime.py"
    replacement = b"operator replacement\n"
    original_identity = installer._receipt_file_identity(runtime, "managed file")
    original_digest = installer._ReceiptParentHandle.digest
    swapped = False

    def replace_after_identity(handle: object, name: str) -> str:
        nonlocal swapped
        if (
            name == runtime.name
            and Path(handle.path).resolve() == runtime.parent.resolve()
            and not swapped
        ):
            swapped = True
            runtime.unlink()
            runtime.write_bytes(replacement)
        return original_digest(handle, name)

    monkeypatch.setattr(installer._ReceiptParentHandle, "digest", replace_after_identity)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert swapped
    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert installer._receipt_file_identity(runtime, "managed file") != original_identity
    assert runtime.read_bytes() == replacement


def test_uninstall_rejects_parent_swap_between_validation_and_unlink(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    module = destination / "dcc_mcp_krita"
    attacker = tmp_path / "attacker"
    shutil.copytree(module, attacker)
    receipt = json.loads(
        (destination / ".dcc-mcp" / "receipts" / "krita.json").read_text(encoding="utf-8")
    )
    expected_parent_handles = len(
        {Path(record["path"]).parent for record in receipt["managed_files"]}
    )
    original_init = installer._ReceiptParentHandle.__init__
    parent_handles = 0
    module_opened = False

    def redirect_reopened_parent(handle: object, path: Path) -> None:
        nonlocal parent_handles, module_opened
        parent_handles += 1
        # A vulnerable second pass reopens the module parent by pathname; make
        # that reacquisition resolve to a byte-identical attacker directory.
        if path.resolve() == module.resolve() and module_opened:
            original_init(handle, attacker)
        else:
            original_init(handle, path)
            if path.resolve() == module.resolve():
                module_opened = True

    monkeypatch.setattr(installer._ReceiptParentHandle, "__init__", redirect_reopened_parent)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 0
    # Uninstall also holds the receipt container itself through deletion.
    assert parent_handles == expected_parent_handles + 1
    assert not module.exists()
    assert (attacker / "runtime.py").is_file()


def test_uninstall_rejects_same_content_replacement_after_final_digest(
    tmp_path: Path, monkeypatch
) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    runtime = destination / "dcc_mcp_krita" / "runtime.py"
    original_digest = installer._ReceiptParentHandle.digest
    runtime_digests = 0
    replacement = runtime.read_bytes()
    swapped = False

    def replace_after_final_digest(handle: object, name: str) -> str:
        nonlocal runtime_digests, swapped
        digest = original_digest(handle, name)
        if name == runtime.name and Path(handle.path).resolve() == runtime.parent.resolve():
            runtime_digests += 1
            if runtime_digests == 2:
                runtime.unlink()
                runtime.write_bytes(replacement)
                swapped = True
        return digest

    monkeypatch.setattr(installer._ReceiptParentHandle, "digest", replace_after_final_digest)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert swapped
    assert result["exit_code"] == 10
    assert result["stage"] == "receipt"
    assert runtime.read_bytes() == replacement


def test_uninstall_quarantines_before_private_digest_race(tmp_path: Path, monkeypatch) -> None:
    import dcc_mcp_krita.install as installer
    from dcc_mcp_krita.install import LifecycleRequest, run_lifecycle

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
    )
    assert run_lifecycle(request)["exit_code"] == 0
    runtime = destination / "dcc_mcp_krita" / "runtime.py"
    replacement = runtime.read_bytes()
    original_rename = installer._ReceiptParentHandle._rename
    swapped = False

    def replace_after_quarantine(handle: object, source: str, target: str) -> None:
        nonlocal swapped
        original_rename(handle, source, target)
        if source == runtime.name and not swapped:
            runtime.write_bytes(replacement)
            swapped = True

    monkeypatch.setattr(installer._ReceiptParentHandle, "_rename", replace_after_quarantine)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert swapped
    assert result["exit_code"] == 0
    assert result["status"] == "uninstalled"
    assert runtime.read_bytes() == replacement


def test_reparse_point_attribute_is_rejected_without_is_junction(
    tmp_path: Path, monkeypatch
) -> None:
    import stat

    import dcc_mcp_krita.install as installer

    root = tmp_path / "pykrita"
    root.mkdir()
    reparse = root / "junction"
    victim = reparse / "victim.txt"

    class ReparseStat:
        st_mode = stat.S_IFDIR
        st_file_attributes = 0x0400  # FILE_ATTRIBUTE_REPARSE_POINT

    monkeypatch.setattr(
        installer.os.path,
        "lexists",
        lambda value: str(value) in {str(root), str(reparse)},
    )
    monkeypatch.setattr(installer.os, "lstat", lambda _value: ReparseStat())

    with pytest.raises(installer.LifecycleFailure, match="contains a link"):
        installer._assert_no_reparse_components(root, victim, "managed file")


def test_real_windows_junction_is_rejected_for_receipt_paths(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("junction regression requires Windows")
    import subprocess

    import dcc_mcp_krita.install as installer

    root = tmp_path / "pykrita"
    outside = tmp_path / "operator"
    junction = root / "junction"
    root.mkdir()
    outside.mkdir()
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        pytest.skip("junction creation is unavailable on this runner")
    if result.returncode != 0 or not junction.is_dir():
        pytest.skip("junction creation is unavailable on this runner")

    with pytest.raises(installer.LifecycleFailure, match="contains a link"):
        installer._safe_receipt_path(root, "junction/victim.txt", "managed file")


def _repaired_cache_fixture(tmp_path: Path, monkeypatch, *, prior_cache=True, foreign_tag=False):
    """Compile private fixtures without importing the installed Krita plug-in."""
    import importlib.util
    import py_compile

    import dcc_mcp_krita.install as installer

    class Probe:
        returncode = 0
        stdout = "Krita 5.2.11\n"

    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: Probe())
    destination = tmp_path / "krita" / "pykrita"
    module = destination / "dcc_mcp_krita"
    module.mkdir(parents=True)
    previous = module / "__init__.py"
    private_payload = tmp_path / "payload"
    shutil.copytree(installer._resolve_source_dir(), private_payload)
    payload = private_payload / "dcc_mcp_krita" / "__init__.py"
    payload.write_bytes(b"PREVIOUS = False\n#" + b" " * 100)
    monkeypatch.setattr(installer, "_resolve_source_dir", lambda: private_payload)
    previous_bytes = b"PREVIOUS = True\n#" + b" " * (payload.stat().st_size - 17)
    assert len(previous_bytes) == payload.stat().st_size
    previous.write_bytes(previous_bytes)
    stamp = payload.stat().st_mtime_ns
    os.utime(previous, ns=(stamp, stamp))
    cache = Path(importlib.util.cache_from_source(str(previous)))
    other_tag = "cpython-39" if sys.implementation.cache_tag != "cpython-39" else "cpython-312"
    old_cache = None
    if prior_cache:
        py_compile.compile(
            str(previous), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP
        )
        if foreign_tag:
            foreign = cache.with_name(cache.name.replace(sys.implementation.cache_tag, other_tag))
            cache.rename(foreign)
        old_cache = (foreign if foreign_tag else cache).read_bytes()
    (module / "previous.pyc").write_bytes(b"previous source-less bytecode")
    cache.parent.mkdir(exist_ok=True)
    (cache.parent / "previous_orphan.cpython-39.pyc").write_bytes(b"previous source-less cache")
    dcc_path = tmp_path / "Host" / "krita.exe"
    dcc_path.parent.mkdir()
    dcc_path.touch()
    request = installer.LifecycleRequest(
        operation="install",
        dcc_path=dcc_path,
        python_path=Path(sys.executable),
        destination=destination,
        yes=True,
        repair=True,
    )
    assert installer.run_lifecycle(request)["exit_code"] == 0
    py_compile.compile(
        str(previous), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP
    )
    if foreign_tag:
        foreign = cache.with_name(cache.name.replace(sys.implementation.cache_tag, other_tag))
        cache.rename(foreign)
        cache = foreign
    current_cache = cache.read_bytes()
    if old_cache is not None:
        # A naive skip leaves new bytecode valid for old source with equal mtime/size.
        assert old_cache[8:16] == current_cache[8:16]
        assert old_cache != current_cache
    receipt = destination / ".dcc-mcp" / "receipts" / "krita.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    backup_root = destination / payload["backup"]["root"]
    return installer, request, module, previous_bytes, cache, receipt, backup_root


@pytest.mark.parametrize(
    "prior_cache,foreign_tag",
    [(True, False), (False, False), (True, True)],
    ids=["old-and-new-cache", "new-cache-only", "different-host-tag"],
)
def test_repair_uninstall_invalidates_only_source_backed_generated_cache(
    tmp_path: Path, monkeypatch, prior_cache: bool, foreign_tag: bool
) -> None:
    import importlib.util

    installer, request, module, previous, cache, receipt, _ = _repaired_cache_fixture(
        tmp_path, monkeypatch, prior_cache=prior_cache, foreign_tag=foreign_tag
    )
    operator_files = {
        module / "legacy.pyc": b"source-less legacy bytecode",
        module / "legacy.pyo": b"source-less optimized bytecode",
        cache.parent / "orphan.cpython-39.pyc": b"source-less cache",
        cache.parent / "operator.txt": b"operator-owned notes",
    }
    for path, data in operator_files.items():
        path.write_bytes(data)
    result = installer.run_lifecycle(request.with_operation("uninstall"))
    assert result["exit_code"] == 0
    assert (module / "__init__.py").read_bytes() == previous
    assert not receipt.exists()
    assert all(path.read_bytes() == data for path, data in operator_files.items())
    assert (module / "previous.pyc").read_bytes() == b"previous source-less bytecode"
    assert (
        cache.parent / "previous_orphan.cpython-39.pyc"
    ).read_bytes() == b"previous source-less cache"
    # The only executed module is this private inert old-source fixture.
    spec = importlib.util.spec_from_file_location("restored_cache_probe", module / "__init__.py")
    restored = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restored)
    assert restored.PREVIOUS is True
    assert not cache.exists()


@pytest.mark.parametrize(
    "failure",
    [
        "conflict",
        "cache-replacement",
        "cache-parent-replacement",
        "cache-locked",
        "backup-cache-symlink",
        "runtime-cache-symlink",
        "source-less-conflict",
    ],
)
def test_repair_cache_invalidation_preserves_fail_closed_recovery(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    installer, request, module, _, cache, receipt, backup_root = _repaired_cache_fixture(
        tmp_path, monkeypatch
    )
    receipt_bytes = receipt.read_bytes()
    managed = json.loads(receipt_bytes)["managed_files"]
    managed_bytes = {
        record["path"]: (request.destination / record["path"]).read_bytes() for record in managed
    }
    cache_bytes = cache.read_bytes()
    victim = tmp_path / "operator-victim.txt"
    victim.write_bytes(b"operator victim")
    if failure == "conflict":
        (backup_root / "dcc_mcp_krita" / "operator.txt").write_bytes(b"previous file")
        (module / "operator.txt").write_bytes(b"operator file")
    elif failure == "source-less-conflict":
        relative = Path("dcc_mcp_krita/__pycache__/orphan.cpython-39.pyc")
        (backup_root / relative).write_bytes(b"previous source-less bytecode")
        (request.destination / relative).write_bytes(b"operator source-less bytecode")
    elif failure in {"backup-cache-symlink", "runtime-cache-symlink"}:
        link = (
            backup_root / cache.relative_to(request.destination)
            if failure.startswith("backup")
            else cache
        )
        link.unlink()
        try:
            link.symlink_to(victim)
        except OSError:
            pytest.skip("symlink creation is unavailable on this runner")
    original_backup = {
        path.relative_to(backup_root).as_posix(): os.readlink(path)
        if path.is_symlink()
        else path.read_bytes()
        for path in backup_root.rglob("*")
        if path.is_symlink() or path.is_file()
    }
    interrupted = False
    original_unlink = installer._ReceiptParentHandle.unlink
    original_remove = installer._remove_receipt_owned_files

    def remove_with_parent_swap(destination, records, *args, **kwargs):
        nonlocal interrupted
        if failure == "cache-parent-replacement" and not interrupted:
            interrupted = True
            retained = module / "retained-cache"
            cache.parent.rename(retained)
            cache.parent.mkdir()
            cache.write_bytes(cache_bytes)
        return original_remove(destination, records, *args, **kwargs)

    def interrupt_cache(handle, name, *args, **kwargs):
        nonlocal interrupted
        if name == cache.name and not interrupted:
            interrupted = True
            if failure == "cache-locked":
                raise PermissionError("generated cache is locked")
            if failure == "cache-replacement":
                cache.unlink()
                cache.write_bytes(b"operator cache replacement")
        return original_unlink(handle, name, *args, **kwargs)

    if failure == "cache-parent-replacement":
        monkeypatch.setattr(installer, "_remove_receipt_owned_files", remove_with_parent_swap)
    if failure in {"cache-replacement", "cache-locked"}:
        monkeypatch.setattr(installer._ReceiptParentHandle, "unlink", interrupt_cache)
    result = installer.run_lifecycle(request.with_operation("uninstall"))
    assert result["exit_code"] == (50 if failure == "cache-locked" else 10)
    assert result["stage"] == ("locked_files" if failure == "cache-locked" else "receipt")
    assert receipt.read_bytes() == receipt_bytes
    assert all(
        (request.destination / path).read_bytes() == data for path, data in managed_bytes.items()
    )
    assert {
        path.relative_to(backup_root).as_posix(): os.readlink(path)
        if path.is_symlink()
        else path.read_bytes()
        for path in backup_root.rglob("*")
        if path.is_symlink() or path.is_file()
    } == original_backup
    assert victim.read_bytes() == b"operator victim"
    if failure in {"cache-replacement", "cache-locked", "cache-parent-replacement"}:
        assert interrupted
    if failure == "cache-replacement":
        assert cache.read_bytes() == b"operator cache replacement"
    elif failure != "runtime-cache-symlink":
        assert cache.read_bytes() == cache_bytes
    if failure == "conflict":
        assert (module / "operator.txt").read_bytes() == b"operator file"
        assert "dcc_mcp_krita/operator.txt" in result["reason"]
    if failure == "source-less-conflict":
        assert (
            cache.parent / "orphan.cpython-39.pyc"
        ).read_bytes() == b"operator source-less bytecode"
