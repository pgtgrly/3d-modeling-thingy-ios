#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Send one Blender MCP JSON request, or adapt a local Blender MCP client to a farm worker."""

import argparse
import json
from pathlib import Path
import socket
import socketserver
import sys

# This wire codec has no Blender dependency.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/addons_core/farm_worker"))
import protocol


def forward(local, connect, key):
    """Translate one stock MCP client connection. An idle client can reconnect upstream."""
    try:
        while True:
            command = protocol.read_json(local)
            with connect() as remote:
                reply = protocol.call(remote, key, command)
            local.sendall(protocol.encode(reply))
    except EOFError:
        pass
    except (KeyError, OSError, ValueError) as ex:
        try:
            local.sendall(protocol.encode({"status": "error", "message": str(ex)}))
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="worker device hostname or address")
    parser.add_argument("token_file", type=Path)
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--bridge", type=int, metavar="LOCAL_PORT",
                        help="authorize clients on this Mac via a foreground IPv4 loopback bridge")
    args = parser.parse_args()
    key = args.token_file.read_bytes().strip()

    def connect():
        sock = socket.create_connection((args.host, args.port), timeout=10)
        # Rendering and arbitrary Blender commands have no fixed deadline.
        sock.settimeout(None)
        return sock

    if args.bridge is None:
        with connect() as sock:
            reply = protocol.call(sock, key, json.load(sys.stdin))
        print(json.dumps(reply))
        return int(reply.get("status") != "success")

    class Bridge(socketserver.BaseRequestHandler):
        def handle(self):
            forward(self.request, connect, key)

    class LocalServer(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with LocalServer(("127.0.0.1", args.bridge), Bridge) as server:
        print(f"Blender MCP bridge on 127.0.0.1:{args.bridge}. Press Ctrl-C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
