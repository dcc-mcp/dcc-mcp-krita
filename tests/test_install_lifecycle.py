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


def test_repair_uninstall_restores_preexisting_plugin_files(tmp_path: Path, monkeypatch) -> None:
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
    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 0
    assert desktop.read_text(encoding="utf-8") == "previous desktop\n"
    assert previous_init.read_text(encoding="utf-8") == "PREVIOUS = True\n"


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

    def fail_after_first_restore(target, backup):
        nonlocal calls
        calls += 1
        original_restore(target, backup)
        if calls == 1:
            raise OSError("restore interrupted")

    monkeypatch.setattr(installer, "_restore_backup", fail_after_first_restore)

    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 30
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

    def swap_parent_after_validation(handle: object, name: str) -> None:
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
        original_unlink(handle, name)

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

    def redirect_reopened_parent(handle: object, path: Path) -> None:
        nonlocal parent_handles
        parent_handles += 1
        # A vulnerable second pass reopens the module parent by pathname; make
        # that reacquisition resolve to a byte-identical attacker directory.
        if parent_handles > 2 and path.resolve() == module.resolve():
            original_init(handle, attacker)
        else:
            original_init(handle, path)

    monkeypatch.setattr(installer._ReceiptParentHandle, "__init__", redirect_reopened_parent)
    result = run_lifecycle(request.with_operation("uninstall"))

    assert result["exit_code"] == 0
    assert parent_handles == expected_parent_handles
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
