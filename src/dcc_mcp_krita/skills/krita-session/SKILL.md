---
name: krita-session
description: >-
  Inspect the connected Krita session through the DCC-MCP Python plug-in
  bridge. Use for session health, open images, and active image metadata.
license: MIT
compatibility: "Krita.0+; dcc-mcp-core 0.19+"
allowed-tools: "python"
metadata:
  dcc-mcp:
    dcc: krita
    layer: domain
    version: "0.1.0"
    search-hint: "KRITA image editor session document active image layers"
    tags: "krita,image-editing,session"
    tools: tools.yaml
    depends: "dcc-diagnostics"
---

# KRITA Session

Install and run the bundled Krita plug-in before using this skill. Calls use a
loopback JSON-lines bridge and never execute arbitrary KRITA/Python source.
