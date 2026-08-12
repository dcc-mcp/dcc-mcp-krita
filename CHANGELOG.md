# Changelog

## 0.3.0

- Replace the session-only bridge with 16 typed document, layer, painting, save, and export tools.
- Marshal every LibKis operation through a bounded Qt UI-thread queue.
- Add loopback authentication, allowed roots, size limits, destructive opt-ins, and artifact hashes.
- Add staged plug-in installation with rollback and a machine-readable doctor command.
- Validate Python 3.9/3.12, Skill packaging, workflows, and final distributions.

## [0.2.0](https://github.com/dcc-mcp/dcc-mcp-krita/compare/v0.1.0...v0.2.0) (2026-07-25)


### Features

* add DCC MCP adapter ([fc7aeac](https://github.com/dcc-mcp/dcc-mcp-krita/commit/fc7aeac768c5aff17c7c553a83449e7c962800c9))
* add unified menu with Copy Instance ID, Server Info, and About DCC MCP ([#2](https://github.com/dcc-mcp/dcc-mcp-krita/issues/2)) ([e03addf](https://github.com/dcc-mcp/dcc-mcp-krita/commit/e03addf8f2963254b189772fe44757a5f9e20ebf))


### Documentation

* optimize workflow showcase ([7a37b8d](https://github.com/dcc-mcp/dcc-mcp-krita/commit/7a37b8df6adb34f71cb815d2a52ff739d399599d))
* redesign DCC-MCP brand visuals ([0952d40](https://github.com/dcc-mcp/dcc-mcp-krita/commit/0952d40c4d4e11d719144d8d972281d9d2b4c69a))

## 0.1.0

- Initial Krita session bridge and MCP adapter.
