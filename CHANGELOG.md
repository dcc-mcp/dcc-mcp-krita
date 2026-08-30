# Changelog

## [0.5.0](https://github.com/dcc-mcp/dcc-mcp-krita/compare/v0.4.0...v0.5.0) (2026-08-30)


### Features

* align Krita install staging and skill guidance ([#9](https://github.com/dcc-mcp/dcc-mcp-krita/issues/9)) ([5bd6fc6](https://github.com/dcc-mcp/dcc-mcp-krita/commit/5bd6fc6665e396f696ff6f2c6d3115b263762f67))

## [0.4.0](https://github.com/dcc-mcp/dcc-mcp-krita/compare/v0.3.0...v0.4.0) (2026-08-25)


### Features

* standardize Krita install lifecycle ([793089c](https://github.com/dcc-mcp/dcc-mcp-krita/commit/793089c32cfca40a1366a5c0e9ac137c0e243bda))

## [0.3.0](https://github.com/dcc-mcp/dcc-mcp-krita/compare/v0.2.0...v0.3.0) (2026-08-12)


### Features

* ship production-ready Krita authoring ([#5](https://github.com/dcc-mcp/dcc-mcp-krita/issues/5)) ([98573d8](https://github.com/dcc-mcp/dcc-mcp-krita/commit/98573d8c7093361691cb89255ecb34148d49447b))


### Bug Fixes

* load Krita runtime API during plugin import ([bf3acc0](https://github.com/dcc-mcp/dcc-mcp-krita/commit/bf3acc0f650ad16f5a6bab663ab4f36bb57568e2))

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
