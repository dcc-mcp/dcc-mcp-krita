---
name: krita-document-authoring
description: >-
  Inspect, create, open, layer, paint, save, export, and safely close Krita
  documents through typed commands on Krita's UI thread. Use for deterministic
  2D texture, concept-art, sprite-source, and game-asset handoff workflows. Do
  not use for arbitrary Python execution or unsupported freehand brush control.
license: MIT
compatibility: "Python 3.9+; Krita 5.2+; dcc-mcp-core 0.19+"
allowed-tools: "python"
metadata:
  dcc-mcp:
    dcc: krita
    layer: domain
    version: "0.4.0"  # x-release-please-version
    search-hint: "Krita document layer paint rectangle PNG texture sprite export"
    tags: [krita, digital-painting, textures, layers, game-art, export]
    tools: tools.yaml
---

# Krita Document Authoring

Use this Skill for deterministic document and layer workflows through the
authenticated loopback bridge. Every Krita API call is queued onto the UI main
thread. File operations require explicit `DCC_MCP_KRITA_ALLOWED_ROOTS`.

Start with `get_status`, then use `list_documents` or create/open a document.
Inspect the layer tree before mutations. For programmatic assets, create paint
layers, fill bounded RGBA rectangles, set layer properties, save a layered
`.kra`, and export a PNG/JPEG/WebP/TIFF handoff artifact. Inspect the returned
path, byte size, and SHA-256 before passing the artifact to another DCC.

Flattening, deleting layers, discarding changes, and overwriting files require
explicit typed opt-ins. The bridge never evaluates caller-provided Python,
Krita scripts, shell commands, or free-form action identifiers.
