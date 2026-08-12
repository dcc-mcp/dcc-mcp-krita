import json
import socket
import threading

import pytest

from dcc_mcp_krita.bridge import KritaBridge, KritaBridgeError


def test_bridge_sends_json_lines_request():
    received = {}

    def serve(listener):
        connection, _ = listener.accept()
        with connection:
            received["request"] = json.loads(connection.makefile("r", encoding="utf-8").readline())
            response = {
                "jsonrpc": "2.0",
                "id": received["request"]["id"],
                "result": {"ready": True},
            }
            connection.sendall((json.dumps(response) + "\n").encode())

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    threading.Thread(target=serve, args=(listener,), daemon=True).start()
    bridge = KritaBridge(port=listener.getsockname()[1], token="x" * 32)
    assert bridge.call("krita.ping") == {"ready": True}
    assert received["request"]["method"] == "krita.ping"
    assert received["request"]["token"] == "x" * 32
    listener.close()


def test_bridge_rejects_non_loopback_and_short_token():
    with pytest.raises(KritaBridgeError, match="loopback"):
        KritaBridge(host="192.0.2.10", token="x" * 32)
    with pytest.raises(KritaBridgeError, match="at least 32"):
        KritaBridge(token="short")


def test_bridge_rejects_mismatched_response_id():
    def serve(listener):
        connection, _ = listener.accept()
        with connection:
            connection.makefile("r", encoding="utf-8").readline()
            connection.sendall(b'{"jsonrpc":"2.0","id":"wrong","result":{}}\n')

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    threading.Thread(target=serve, args=(listener,), daemon=True).start()
    bridge = KritaBridge(port=listener.getsockname()[1], token="x" * 32)
    with pytest.raises(KritaBridgeError, match="mismatched"):
        bridge.call("krita.get_status")
    listener.close()


def test_bridge_surfaces_stable_host_error_message():
    def serve(listener):
        connection, _ = listener.accept()
        with connection:
            request = json.loads(connection.makefile("r", encoding="utf-8").readline())
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": "bridge_error", "message": "typed request rejected"},
            }
            connection.sendall((json.dumps(response) + "\n").encode())

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    threading.Thread(target=serve, args=(listener,), daemon=True).start()
    bridge = KritaBridge(port=listener.getsockname()[1], token="x" * 32)
    with pytest.raises(KritaBridgeError, match="typed request rejected"):
        bridge.call("krita.get_status")
    listener.close()


def test_bridge_rejects_invalid_method_and_timeout():
    bridge = KritaBridge(token="x" * 32)
    with pytest.raises(KritaBridgeError, match=r"krita\.\*"):
        bridge.call("python.eval")
    with pytest.raises(KritaBridgeError, match="timeout_secs"):
        bridge.call("krita.open_document", timeout_secs=1801)
