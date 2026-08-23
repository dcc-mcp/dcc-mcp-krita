"""Unified Krita adapter entry point with lifecycle subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .__version__ import __version__
from .install import LifecycleRequest, run_lifecycle

_LIFECYCLE_OPERATIONS = ("install", "status", "verify", "uninstall", "upgrade")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the DCC-MCP Krita adapter or its installer")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in _LIFECYCLE_OPERATIONS:
        command = subparsers.add_parser(operation, help="%s the Krita plug-in" % operation)
        command.add_argument("--dcc-path", type=Path, help="Path to the Krita executable")
        command.add_argument("--python", type=Path, default=Path(sys.executable))
        command.add_argument("--destination", type=Path, help="Override the pykrita directory")
        command.add_argument("--version", default=__version__)
        command.add_argument("--yes", action="store_true")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--json", action="store_true", dest="json_output")
        command.add_argument("--repair", action="store_true")
    return parser


def _print_human(result: dict[str, object]) -> None:
    print("%s: %s" % (result["status"], result["reason"]))
    for step in result.get("next_steps", []):
        if isinstance(step, dict):
            print("Next: %s" % step.get("description", step.get("id", "follow instructions")))


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        from .server import main as server_main

        server_main()
        return 0
    if arguments[0] in {"-h", "--help"}:
        _parser().print_help()
        return 0
    if arguments[0] not in _LIFECYCLE_OPERATIONS:
        _parser().error("unknown command: %s" % arguments[0])
    args = _parser().parse_args(arguments)
    request = LifecycleRequest(
        operation=args.operation,
        dcc_path=args.dcc_path,
        python_path=args.python,
        destination=args.destination,
        version=args.version,
        yes=args.yes,
        dry_run=args.dry_run,
        json_output=args.json_output,
        repair=args.repair,
    )
    result = run_lifecycle(request)
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(result)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
