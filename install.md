# Install DCC-MCP Krita

The canonical copy of this guide is:
https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-krita/main/install.md

## Requirements

- Krita 5.2+ installed locally;
- Python 3.9+ with `dcc-mcp-core` 0.19.38+ and this adapter installed;
- permission to update the current user's Krita resource and configuration
  directories.

Krita uses its embedded Python for the plug-in. `--python` selects and validates
the external installer runtime; live verification reports the embedded runtime.

## Supported versions

| Component | Supported |
| --- | --- |
| Krita | 5.2+ |
| Installer Python | 3.9+ |
| `dcc-mcp-core` | 0.19.38 to less than 1.0 |
| Operating systems | Windows, macOS, Linux |

## Manual path

Install the signed release published by the project, or a wheel obtained from a
trusted release artifact:

```bash
python -m pip install dcc-mcp-krita
python -m pip install ./dcc_mcp_krita-VERSION-py3-none-any.whl
```

Do not execute an unverified download. The adapter does not fetch a mutable
installer payload or run an arbitrary shell command.

## Agent quick path

Pass `--dcc-path` when Krita is not on `PATH`. The CLI also accepts `--python`,
`--destination`, `--version`, `--yes`, `--dry-run`, `--json`, and `--repair` on
every lifecycle verb. Mutating commands require `--yes`; `--dry-run` performs
preflight without changing files.

```bash
dcc-mcp-krita install --dcc-path /path/to/krita --yes --json
dcc-mcp-krita status --dcc-path /path/to/krita --json
dcc-mcp-krita verify --dcc-path /path/to/krita --json
dcc-mcp-krita upgrade --dcc-path /path/to/krita --yes --json
dcc-mcp-krita uninstall --dcc-path /path/to/krita --yes --json
```

The installer stages replacement, records file digests in
`.dcc-mcp/receipts/krita.json`, and retains an adapter-owned backup when it
replaces pre-existing plug-in files. Uninstall consumes that receipt and restores
the backup. A partial install fails closed until `install --repair --yes` is
explicitly requested. Loaded or locked artifacts return a restart-required
result instead of forcing replacement.

Default plug-in and configuration locations are:

| Platform | `pykrita` plug-in directory | Krita configuration |
| --- | --- | --- |
| Windows | `%APPDATA%\krita\pykrita` | `%LOCALAPPDATA%\kritarc` |
| macOS | `~/Library/Application Support/Krita/pykrita` | `~/Library/Preferences/kritarc` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/krita/pykrita` | `${XDG_CONFIG_HOME:-~/.config}/kritarc` |

## Verify

Close Krita before editing its configuration. Then restart Krita and enable
**DCC MCP Krita** in **Settings → Configure Krita → Python Plugin Manager**.
The JSON result supplies the exact `[python] enable_dcc_mcp_krita=true` INI edit
as a machine-readable `next_step`; the Plugin Manager remains the supported GUI
alternative.

Start Krita with the same bridge token configuration as the adapter, then run:

```bash
dcc-mcp-krita verify --dcc-path /path/to/krita --json
```

Verification reports success only when the receipt and hashes match, the plug-in
is enabled, no post-install bootstrap error is present, and the authenticated
live bridge answers `krita.get_status`. CI cannot substitute for this live-host
gate.

## Upgrade

Close Krita, install the trusted new wheel, then run the receipt-aware upgrade:

```bash
dcc-mcp-krita upgrade --dcc-path /path/to/krita --yes --json
dcc-mcp-krita verify --dcc-path /path/to/krita --json
```

If files are loaded or locked, exit `50` instructs the caller to close or restart
Krita before retrying. A failed replacement restores the prior files and receipt.

## Uninstall

Close Krita and use the receipt-owned uninstall path:

```bash
dcc-mcp-krita uninstall --dcc-path /path/to/krita --yes --json
```

Uninstall removes only receipt-owned files and restores any plug-in files that
were present before the adapter install. Missing, invalid, or partial receipts
fail closed rather than deleting unowned content.

## JSON and exit codes

`--json` writes one JSON document with `schema_version`, `operation`, `status`,
`exit_code`, detected versions and paths, `receipt_path`, `verify`, and exact
`next_steps`.

| Exit | Meaning |
| --- | --- |
| `0` | Success, including an idempotent absent/present status |
| `10` | Preflight, compatibility, confirmation, receipt, or partial-state failure |
| `20` | Artifact acquisition or integrity failure |
| `30` | Install, rollback, or filesystem failure |
| `40` | Verification failed or the live host is not usable |
| `50` | Krita must be closed or restarted before retrying |

## Troubleshooting

- `host`: use the executable inside `krita.app/Contents/MacOS/krita` on macOS,
  or pass the full executable with `--dcc-path`.
- `python` or `core`: install with Python 3.9+ and upgrade `dcc-mcp-core` to
  0.19.38 or newer.
- `partial_install`: inspect `status --json`, close Krita, then use
  `install --repair --yes`.
- `enablement`: close Krita, enable the plug-in with Python Plugin Manager (or
  apply the exact returned INI edit), and restart Krita.
- `bootstrap`: inspect `~/.dcc-mcp/krita-bootstrap-errors.jsonl` (or
  `DCC_MCP_KRITA_BOOTSTRAP_ERRORS`) for the bounded error record, correct the
  reported dependency or configuration problem, and restart Krita.
- `host_readiness`: confirm Krita is running, both processes use the same
  loopback bridge port and token source, then run `verify` again.

The compatibility commands `dcc-mcp-krita-install` and
`dcc-mcp-krita-doctor` remain available for existing deployments, but new
automation should use the standard lifecycle verbs above.
