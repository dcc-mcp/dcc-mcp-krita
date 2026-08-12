# Architecture

## Ownership boundary

`dcc-mcp-krita` has two processes with one narrow protocol:

```text
MCP client
  -> dcc-mcp-core Skill/job runtime (normal Python)
    -> authenticated loopback JSON line
      -> Krita Python extension socket worker
        -> bounded command queue
          -> 10 ms Qt timer on Krita's UI thread
            -> fixed LibKis operation
```

The external service owns MCP discovery, jobs, typed schemas, and cancellation.
The extension owns Krita lifecycle and thread affinity. Socket worker threads
only parse/authenticate/enqueue requests and serialize results.

## Transport

- bind address: `127.0.0.1` only;
- one request and one response per connection;
- JSON-RPC correlation IDs;
- random 256-bit-class bearer token from environment or a per-user token file;
- 1 MiB request and 16 MiB client response limits;
- 32 queued UI commands, eight drained per timer tick;
- 1–1,800 second bounded command deadlines;
- stable error codes without tracebacks, secrets, or unrelated paths.

Document IDs are instance-scoped opaque values. Layer IDs come from Krita's
`Node.uniqueId()`. They are resolved again inside the current document before
each mutation.

## File boundary

File operations are disabled until `DCC_MCP_KRITA_ALLOWED_ROOTS` contains at
least one root. Inputs and outputs are resolved before containment checks, so
links cannot escape the workspace. The adapter restricts input/output suffixes,
input size, output existence, and overwrite intent. Document metadata exposes a
full path only when that path is inside the configured roots.

`save_document` writes layered `.kra`. `export_document` accepts a bounded
format allowlist and known PNG/JPEG options, enables Krita batch mode for the
call, verifies a non-empty regular artifact, and returns SHA-256.

## Typed host operations

The catalog contains 16 commands grouped as:

- session: status, list documents, active document;
- inspection: inspect document, list layers;
- lifecycle: create, open, save, export, close;
- layer authoring: create paint layer, fill rectangle, set properties, set
  active layer, delete layer, flatten document.

There is no generic `execute`, `action`, `eval`, or script command.

## Failure semantics

Authentication failures stop before dispatch. A full queue rejects immediately.
Timed-out queued commands are marked cancelled and skipped if they have not
started. LibKis exceptions are reduced to a stable host-command error without a
traceback. Existing exports are rejected unless `overwrite=true`; modified
documents cannot close unless `discard_changes=true`; flattening requires
`confirm=true`.

## Installation

The installer stages the desktop file and Python package inside the target
`pykrita` directory, renames any previous installation to a unique backup,
promotes both staged entries, and restores backups if promotion fails. A Krita
restart is required because Python plug-ins load at application startup.
