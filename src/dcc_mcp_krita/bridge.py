"""Authenticated, bounded JSON-lines client for the Krita host bridge."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import time
from pathlib import Path
from typing import Any, Optional

_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_TIMEOUT_SECS = 1_800.0


class KritaBridgeError(RuntimeError):
    """The Krita bridge is unavailable or rejected a typed operation."""


def _token_path() -> Path:
    configured = os.environ.get("DCC_MCP_KRITA_BRIDGE_TOKEN_FILE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home().joinpath(".dcc-mcp", "krita-bridge-token").resolve()


def _load_or_create_token() -> str:
    configured = os.environ.get("DCC_MCP_KRITA_BRIDGE_TOKEN", "")
    if configured:
        if len(configured) < 32:
            raise KritaBridgeError("DCC_MCP_KRITA_BRIDGE_TOKEN must contain at least 32 characters")
        return configured
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(token)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return token
    except FileExistsError:
        for _attempt in range(10):
            try:
                existing = path.read_text(encoding="utf-8").strip()
            except OSError:
                existing = ""
            if len(existing) >= 32:
                return existing
            time.sleep(0.02)
    raise KritaBridgeError("Krita bridge token file is missing, unreadable, or invalid")


class KritaBridge:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3848,
        timeout: float = 120.0,
        token: Optional[str] = None,
    ) -> None:
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise KritaBridgeError("Krita bridge host must be loopback")
        if isinstance(port, bool) or not isinstance(port, int) or port < 1 or port > 65_535:
            raise KritaBridgeError("Krita bridge port must be between 1 and 65535")
        timeout = float(timeout)
        if timeout <= 0 or timeout > _MAX_TIMEOUT_SECS:
            raise KritaBridgeError("Krita bridge timeout must be between 0 and 1800 seconds")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.token = token or _load_or_create_token()
        if len(self.token) < 32:
            raise KritaBridgeError("Krita bridge token must contain at least 32 characters")

    @classmethod
    def from_env(cls) -> "KritaBridge":
        return cls(
            host=os.environ.get("DCC_MCP_KRITA_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("DCC_MCP_KRITA_BRIDGE_PORT", "3848")),
            timeout=float(os.environ.get("DCC_MCP_KRITA_BRIDGE_TIMEOUT", "120")),
        )

    def call(self, method: str, **params: Any) -> Any:
        if not isinstance(method, str) or not method.startswith("krita.") or len(method) > 128:
            raise KritaBridgeError("Krita method must use the typed krita.* namespace")
        request_id = secrets.token_hex(16)
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "token": self.token,
                "method": method,
                "params": params,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        effective_timeout = self.timeout
        requested_timeout = params.get("timeout_secs")
        if requested_timeout is not None:
            if isinstance(requested_timeout, bool) or not isinstance(
                requested_timeout, (int, float)
            ):
                raise KritaBridgeError("timeout_secs must be a number")
            if requested_timeout <= 0 or requested_timeout > _MAX_TIMEOUT_SECS:
                raise KritaBridgeError("timeout_secs must be between 0 and 1800 seconds")
            effective_timeout = max(effective_timeout, float(requested_timeout) + 5.0)
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=effective_timeout
            ) as connection:
                connection.settimeout(effective_timeout)
                connection.sendall(request + b"\n")
                response = connection.makefile("rb").readline(_MAX_RESPONSE_BYTES + 1)
        except OSError as exc:
            raise KritaBridgeError(
                "Krita bridge unavailable at %s:%s; install, enable, and restart the plug-in"
                % (self.host, self.port)
            ) from exc
        if not response:
            raise KritaBridgeError("Krita bridge closed the connection without a response")
        if len(response) > _MAX_RESPONSE_BYTES or not response.endswith(b"\n"):
            raise KritaBridgeError("Krita bridge response is incomplete or oversized")
        try:
            payload = json.loads(response.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise KritaBridgeError("Krita bridge returned invalid UTF-8 JSON") from exc
        if not isinstance(payload, dict) or not hmac.compare_digest(
            str(payload.get("id", "")), request_id
        ):
            raise KritaBridgeError("Krita bridge returned a mismatched response id")
        error = payload.get("error")
        if isinstance(error, dict):
            raise KritaBridgeError(str(error.get("message", "Krita bridge rejected the request")))
        return payload.get("result")


def get_bridge() -> KritaBridge:
    return KritaBridge.from_env()
