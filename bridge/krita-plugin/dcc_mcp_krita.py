#!/usr/bin/env python3
"""Krita Python plug-in exposing a loopback JSON-lines bridge."""

import json
import os
import socketserver

from krita import Krita

PORT = int(os.environ.get("DCC_MCP_KRITA_BRIDGE_PORT", "3848"))


def document_info(document):
    return {"name": document.name(), "width": document.width(), "height": document.height()}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        request = json.loads(self.rfile.readline())
        method = request.get("method")
        app = Krita.instance()
        documents = app.documents()
        if method in {"krita.get_status", "krita.ping"}:
            result = {"ready": True, "krita_version": app.version(), "bridge_port": PORT}
        elif method in {"krita.list_documents", "krita.list_images"}:
            result = [document_info(document) for document in documents]
        elif method in {"krita.get_active_document", "krita.get_active_image"}:
            document = app.activeDocument()
            result = document_info(document) if document else None
        else:
            result = {"error": f"Unsupported Krita bridge method: {method}"}
        self.wfile.write((json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}) + "\n").encode())


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


Server(("127.0.0.1", PORT), Handler).serve_forever()
