"""Tests for Krita plugin installation and module structure."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import types
from pathlib import Path, PurePosixPath

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

# ── Install tests ────────────────────────────────────────────────────────────


class TestDefaultPykritaDir:
    """Platform-specific pykrita directory resolution."""

    @pytest.mark.skipif(os.name != "nt", reason="WindowsPath not available on Linux")
    def test_windows_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setenv("APPDATA", "C:\\Users\\test\\AppData\\Roaming")
        from dcc_mcp_krita.install import default_pykrita_dir

        result = default_pykrita_dir()
        assert result == Path("C:/Users/test/AppData/Roaming/krita/pykrita")

    @pytest.mark.skipif(os.name != "nt", reason="WindowsPath not available on Linux")
    def test_windows_fallback_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setattr(Path, "home", lambda: Path("C:/Users/test"))
        from dcc_mcp_krita.install import default_pykrita_dir

        result = default_pykrita_dir()
        assert result == Path("C:/Users/test/AppData/Roaming/krita/pykrita")

    @pytest.mark.skipif(os.name == "nt", reason="PosixPath not available on Windows")
    def test_linux_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", "/home/test/.local/share")
        from dcc_mcp_krita.install import default_pykrita_dir

        result = default_pykrita_dir()
        assert result == Path("/home/test/.local/share/krita/pykrita")

    @pytest.mark.skipif(os.name == "nt", reason="PosixPath not available on Windows")
    def test_linux_fallback_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: Path("/home/test"))
        from dcc_mcp_krita.install import default_pykrita_dir

        result = default_pykrita_dir()
        assert result == Path("/home/test/.local/share/krita/pykrita")

    def test_macos_default_uses_krita_resource_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dcc_mcp_krita.install import default_pykrita_dir

        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: PurePosixPath("/Users/test"))

        result = default_pykrita_dir()

        assert result.as_posix() == "/Users/test/Library/Application Support/Krita/pykrita"


class TestInstall:
    """Integration tests for the install process."""

    def test_install_copies_desktop_and_module(self, tmp_path: Path) -> None:
        """install() copies both the .desktop file and the module directory."""
        from dcc_mcp_krita.install import install

        install(tmp_path)
        assert (tmp_path / "dcc_mcp_krita.desktop").is_file()
        assert (tmp_path / "dcc_mcp_krita" / "__init__.py").is_file()
        assert (tmp_path / "dcc_mcp_krita" / "runtime.py").is_file()

    def test_install_desktop_content(self, tmp_path: Path) -> None:
        """Desktop entry file contains the expected metadata."""
        from dcc_mcp_krita.install import install

        install(tmp_path)
        content = (tmp_path / "dcc_mcp_krita.desktop").read_text(encoding="utf-8")
        assert "DCC MCP" in content
        assert "Krita/PythonPlugin" in content
        assert "X-Krita-Version" in content

    def test_install_module_is_valid_python(self, tmp_path: Path) -> None:
        """The installed __init__.py is syntactically valid Python."""
        from dcc_mcp_krita.install import install

        install(tmp_path)
        source = (tmp_path / "dcc_mcp_krita" / "__init__.py").read_text(encoding="utf-8")
        ast.parse(source)  # raises SyntaxError on failure

    def test_install_creates_target_if_missing(self, tmp_path: Path) -> None:
        """install() creates the pykrita directory if it does not exist."""
        from dcc_mcp_krita.install import install

        target = tmp_path / "new" / "pykrita"
        assert not target.exists()
        install(target)
        assert target.is_dir()
        assert (target / "dcc_mcp_krita.desktop").is_file()

    def test_install_overwrites_existing_module(self, tmp_path: Path) -> None:
        """Re-installing replaces the existing module directory."""
        from dcc_mcp_krita.install import install

        install(tmp_path)
        # Second install — should not raise
        install(tmp_path)
        # Module should still be present after second install
        assert (tmp_path / "dcc_mcp_krita" / "__init__.py").is_file()

    def test_install_rolls_back_both_entries_when_promotion_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import dcc_mcp_krita.install as installer

        installer.install(tmp_path)
        marker = tmp_path / "dcc_mcp_krita" / "previous.txt"
        marker.write_text("previous", encoding="utf-8")
        real_replace = installer.os.replace

        def fail_module_promotion(source: str, destination: str) -> None:
            if ".dcc-mcp-krita-install-" in source and Path(destination).name == "dcc_mcp_krita":
                raise OSError("simulated promotion failure")
            real_replace(source, destination)

        monkeypatch.setattr(installer.os, "replace", fail_module_promotion)
        with pytest.raises(OSError, match="simulated"):
            installer.install(tmp_path)
        assert marker.read_text(encoding="utf-8") == "previous"
        assert (tmp_path / "dcc_mcp_krita.desktop").is_file()
        assert not list(tmp_path.glob(".*.backup-*"))

    def test_doctor_reports_installation_without_token_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dcc_mcp_krita.install import doctor, install

        monkeypatch.setenv("DCC_MCP_KRITA_CONFIG", str(tmp_path / "kritarc"))
        assert doctor(tmp_path)["ready"] is False
        install(tmp_path)
        result = doctor(tmp_path)
        assert result["ready"] is True
        assert result["plugin_enabled"] is False
        assert result["receipt_present"] is False
        assert result["directly_usable"] is False
        assert "token" not in result


# ── Plugin module validation ─────────────────────────────────────────────────


class TestPluginModule:
    """Validate the plugin module structure."""

    def test_plugin_init_exists(self) -> None:
        """The __init__.py exists in the source tree."""
        repo_root = Path(__file__).resolve().parents[1]
        init_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "__init__.py"
        assert init_path.is_file(), f"Missing: {init_path}"

    def test_plugin_desktop_exists(self) -> None:
        """The .desktop file exists in the source tree."""
        repo_root = Path(__file__).resolve().parents[1]
        desktop_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita.desktop"
        assert desktop_path.is_file(), f"Missing: {desktop_path}"

    def test_plugin_init_is_valid_python(self) -> None:
        """The __init__.py parses as valid Python 3.9+."""
        repo_root = Path(__file__).resolve().parents[1]
        init_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "__init__.py"
        source = init_path.read_text(encoding="utf-8")
        ast.parse(source)

    def test_plugin_imports_and_registers_with_krita(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The plugin loads with Krita's runtime module and registers its extension."""
        registered_extensions: list[object] = []
        app = types.SimpleNamespace(addExtension=registered_extensions.append)

        class FakeExtension:
            def __init__(self, parent: object) -> None:
                self.parent = parent

        class FakeKrita:
            @staticmethod
            def instance() -> object:
                return app

        krita_module = types.ModuleType("krita")
        krita_module.Extension = FakeExtension  # type: ignore[attr-defined]
        krita_module.Krita = FakeKrita  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "krita", krita_module)

        repo_root = Path(__file__).resolve().parents[1]
        init_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "_dcc_mcp_krita_plugin_test",
            init_path,
            submodule_search_locations=[str(init_path.parent)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)

        assert len(registered_extensions) == 1
        assert isinstance(registered_extensions[0], module.DccMcpKritaExtension)

    def test_plugin_captures_bridge_bootstrap_failures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registered_extensions: list[object] = []
        app = types.SimpleNamespace(addExtension=registered_extensions.append)

        class FakeExtension:
            def __init__(self, parent: object) -> None:
                self.parent = parent

        class FakeKrita:
            @staticmethod
            def instance() -> object:
                return app

        krita_module = types.ModuleType("krita")
        krita_module.Extension = FakeExtension  # type: ignore[attr-defined]
        krita_module.Krita = FakeKrita  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "krita", krita_module)
        error_log = tmp_path / "bootstrap-errors.jsonl"
        monkeypatch.setenv("DCC_MCP_KRITA_BOOTSTRAP_ERRORS", str(error_log))
        repo_root = Path(__file__).resolve().parents[1]
        init_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "_dcc_mcp_krita_plugin_bootstrap_test",
            init_path,
            submodule_search_locations=[str(init_path.parent)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        monkeypatch.setattr(
            module,
            "start_bridge",
            lambda: (_ for _ in ()).throw(RuntimeError("bridge startup failed")),
        )

        with pytest.raises(RuntimeError, match="bridge startup failed"):
            registered_extensions[0].setup()  # type: ignore[attr-defined]

        event = json.loads(error_log.read_text(encoding="utf-8"))
        assert event["stage"] == "start_bridge"
        assert event["error_type"] == "RuntimeError"
        assert event["adapter_version"] == "0.3.0"

    def test_plugin_init_contains_menu_actions(self) -> None:
        """The plugin module defines the three unified menu action functions."""
        repo_root = Path(__file__).resolve().parents[1]
        init_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "__init__.py"
        source = init_path.read_text(encoding="utf-8")
        assert "_copy_instance_id" in source
        assert "_show_server_info" in source
        assert "_show_about" in source

    def test_plugin_init_contains_clipboard_helper(self) -> None:
        """The plugin module defines the clipboard helper."""
        repo_root = Path(__file__).resolve().parents[1]
        init_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "__init__.py"
        source = init_path.read_text(encoding="utf-8")
        assert "_set_clipboard_text" in source
        assert "QApplication.clipboard" in source or "clipboard()" in source

    def test_plugin_init_references_project_url(self) -> None:
        """The About dialog references the correct GitHub URL."""
        repo_root = Path(__file__).resolve().parents[1]
        init_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "__init__.py"
        source = init_path.read_text(encoding="utf-8")
        assert "github.com/dcc-mcp/dcc-mcp-krita" in source

    def test_old_single_file_removed(self) -> None:
        """The old dcc_mcp_krita.py single-file plugin has been removed."""
        repo_root = Path(__file__).resolve().parents[1]
        old_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita.py"
        assert not old_path.exists(), (
            "Old single-file bridge plugin still exists — should be replaced by the "
            "dcc_mcp_krita/ directory structure"
        )


# ── Version consistency ──────────────────────────────────────────────────────


class TestVersionConsistency:
    """Ensure version strings stay aligned."""

    def test_pyproject_version_matches_init(self) -> None:
        """pyproject.toml version matches src/dcc_mcp_krita/__version__.py."""
        repo_root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
        pyproject_version = pyproject["project"]["version"]

        # Read __version__.py
        version_path = repo_root / "src" / "dcc_mcp_krita" / "__version__.py"
        version_ns: dict = {}
        exec(version_path.read_text(encoding="utf-8"), version_ns)
        assert pyproject_version == version_ns["__version__"]

    def test_pyproject_version_matches_plugin_init(self) -> None:
        """pyproject.toml version matches the hard-coded VERSION in the plugin."""
        repo_root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
        pyproject_version = pyproject["project"]["version"]

        runtime_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "runtime.py"
        source = runtime_path.read_text(encoding="utf-8")
        assert f'VERSION: str = "{pyproject_version}"' in source


# ── Python version compliance ────────────────────────────────────────────────


class TestPythonCompliance:
    """Ensure the plugin code is compatible with the project's minimum Python."""

    def test_union_type_syntax(self) -> None:
        """Verify that `X | Y` union syntax is valid (requires Python 3.10+, but
        we have ``from __future__ import annotations`` so it's parseable on 3.9+).
        """
        # On Python 3.9, `int | None` would be a TypeError at runtime without
        # ``from __future__ import annotations``. Test that the plugin uses the
        # future import and parses cleanly.
        repo_root = Path(__file__).resolve().parents[1]
        runtime_path = repo_root / "bridge" / "krita-plugin" / "dcc_mcp_krita" / "runtime.py"
        source = runtime_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # The file must have the future import as its first import
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in ast.iter_child_nodes(tree)
        ), "Plugin __init__.py must have `from __future__ import annotations`"
