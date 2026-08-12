# dcc-mcp-krita

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/dcc-mcp-krita-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/images/dcc-mcp-krita.svg">
    <img src="docs/images/dcc-mcp-krita.svg" alt="DCC-MCP · KRITA" width="600">
  </picture>
</p>

Typed document, layer, painting, save, and export automation for Krita.

![Krita game-art workflow](docs/images/krita-showcase.webp)

_Illustrative workflow generated with OpenAI ImageGen from the retained source in `docs/images/sources`; it is not a Krita screenshot or host-validation artifact._

The adapter combines an external DCC-MCP service with a small Krita Python
extension. The extension accepts authenticated loopback JSON-lines requests,
queues every LibKis call onto Krita's UI main thread, and exposes only a fixed
typed command catalog. It never evaluates caller-provided Python or action IDs.

## Capabilities

- discover the live bridge and list or inspect open documents;
- create bounded RGBA/U8 documents or open supported files under allowed roots;
- inspect layer hierarchy and create, activate, rename, lock, hide, fade, or
  delete paint layers;
- write bounded typed-color rectangles directly to paint-layer pixels;
- preserve layered work as `.kra` and export PNG, JPEG, WebP, or TIFF artifacts;
- return artifact size and SHA-256 for downstream Blender, Godot, or engine
  import validation;
- flatten or discard modified documents only with explicit typed confirmation.

The bundled `krita-document-authoring` Skill exposes 16 tools. Freehand brush
simulation, arbitrary Python, generic menu actions, and unrestricted filesystem
access are intentionally outside the contract.

## Install

```bash
pip install dcc-mcp-krita
dcc-mcp-krita-install
```

Restart Krita, open **Settings → Configure Krita → Python Plugin Manager**, and
enable **DCC MCP Krita**. Configure allowed file roots before starting both
Krita and the adapter:

```powershell
$env:DCC_MCP_KRITA_ALLOWED_ROOTS = "C:\art\textures;D:\project\sprites"
krita.exe
dcc-mcp-krita
```

On POSIX systems, separate roots with `:` instead of `;`. The bridge defaults
to `127.0.0.1:3848`; `DCC_MCP_KRITA_BRIDGE_PORT` changes it for both processes.
The extension and adapter share a random token through the current user's
`~/.dcc-mcp/krita-bridge-token`; set `DCC_MCP_KRITA_BRIDGE_TOKEN` or
`DCC_MCP_KRITA_BRIDGE_TOKEN_FILE` when deployment policy requires another
secret source.

Inspect installation state without revealing the token:

```bash
dcc-mcp-krita-doctor
```

## Safety model

- loopback-only authenticated transport with bounded requests and responses;
- a bounded main-thread queue; socket workers never call Krita APIs;
- workspace-root, suffix, file-size, pixel-count, layer-count, and timeout limits;
- instance-scoped document and layer IDs instead of caller-provided expressions;
- explicit overwrite, flatten, and discard opt-ins;
- batch-mode export with bounded format options and artifact hashing;
- staged extension installation with rollback if replacement fails.

See [Architecture](docs/architecture.md) for the runtime and failure contracts.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests tools bridge
python -m ruff format --check src tests tools bridge
python tools/lint_skills.py
python -m build
python -m twine check dist/*
```

The host implementation follows Krita's official
[Python plug-in guide](https://docs.krita.org/en/user_manual/python_scripting/krita_python_plugin_howto.html)
and [LibKis API](https://api.kde.org/legacy/krita/html/classDocument.html).
