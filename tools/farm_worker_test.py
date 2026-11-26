#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the actual worker inside desktop Blender, with a disposable local farm."""

import argparse
import base64
import concurrent.futures
import ctypes
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "scripts/addons_core"
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def exercise(directory, pairs):
    import addon_utils
    import bpy

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ADDONS))
    sys.path.insert(0, str(ROOT / "tools"))
    import farm_worker_client
    import farm_worker
    from farm_worker import protocol
    from farm_worker.jobs import Farm

    assert bpy.app.version[:2] == (5, 3), bpy.app.version_string
    token = secrets.token_hex(32)
    documents = directory / "Documents"
    documents.mkdir()
    (documents / "secret").write_text(token)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(directory / "farm.pem", directory / "farm.key")
    uploads = {}
    completed = []
    pulls = []
    prefix = "/" + token
    piece = {
        "id": "p1",
        "files": {"project/a.txt": base64.b64encode(b"input").decode()},
        "script": (
            "import threading\nassert threading.current_thread() is threading.main_thread()\n"
            "def farm_steps():\n"
            "    ticks = []\n"
            "    bpy.app.timers.register(lambda: ticks.append(True))\n"
            "    yield\n"
            "    assert ticks, 'Blender did not service another timer between steps'\n"
            "    (output_dir / 'answer.txt').write_text("
            "(input_dir / 'project/a.txt').read_text() + ':' + bpy.context.scene.name)\n"
        ),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # The URL contains the test credential.

        def do_GET(self):
            assert self.path == prefix + "/next?runtime=blender"
            pulls.append(1)
            self.send_response(200 if len(pulls) == 1 else 204)
            body = json.dumps(piece).encode() if len(pulls) == 1 else b""
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self):
            assert self.path == prefix + "/pieces/p1/files/answer.txt"
            data = self.rfile.read(int(self.headers["Content-Length"]))
            uploads.setdefault("answer.txt", []).append(data)
            # Lose the first acknowledgement and verify an idempotent retry.
            self.send_response(503 if len(uploads["answer.txt"]) == 1 else 204)
            self.end_headers()

        def do_POST(self):
            assert self.path == prefix + "/pieces/p1/complete"
            completed.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

    from contextlib import ExitStack
    with ExitStack() as stack:
        if pairs:
            # Exercise both wire protocols where the host prohibits INET bind.
            # Only the listen/connect boundary is replaced.
            def http_connect(connection):
                connection.sock, peer = socket.socketpair()

                def serve():
                    with peer, tls.wrap_socket(peer, server_side=True) as secured:
                        Handler(secured, ("127.0.0.1", 1), None)
                        # Finish the TLS record stream before releasing the socket.
                        try:
                            secured.unwrap().close()
                        except (ssl.SSLError, OSError):
                            pass
                threading.Thread(target=serve, daemon=True).start()

            stack.enter_context(patch.object(http.client.HTTPConnection, "connect", http_connect))
            import queue
            pending = queue.Queue()

            class Listener:
                def settimeout(self, timeout):
                    self.timeout = timeout

                def accept(self):
                    try:
                        return pending.get(timeout=self.timeout), ("127.0.0.1", 1)
                    except queue.Empty:
                        raise TimeoutError from None

                def close(self):
                    pass

            stack.enter_context(patch.object(socket, "create_server", return_value=Listener()))

            def connect():
                client, peer = socket.socketpair()
                pending.put(peer)
                return client

            farm_port, port = 1, 9876
        else:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            stack.callback(server.server_close)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            farm_port = server.server_port
            with socket.create_server(("127.0.0.1", 0)) as probe:
                port = probe.getsockname()[1]

            def connect():
                return socket.create_connection(("127.0.0.1", port), timeout=10)

        config = {"server_url": f"https://127.0.0.1:{farm_port}", "token_file": "secret",
                  "ca_file": str(directory / "farm.pem")}
        (documents / "farm.json").write_text(json.dumps(config))
        stack.enter_context(patch.object(Path, "home", return_value=directory))
        stack.enter_context(patch.object(sys, "argv", ["Blender", "--", "--mcp-port", str(port)]))
        assert farm_worker.configuration(directory, []) is None
        options = farm_worker.configuration(documents, [])
        assert options["mcp_port"] == 9876
        cli = farm_worker.configuration(documents, ["--farm-worker", "https://farm.test", "other"])
        assert cli["server_url"] == "https://farm.test" and cli["token_file"] == "other"
        for invalid in ("/escape", "../escape", "a/../escape"):
            try:
                Farm.prepare({"files": {invalid: "YQ=="}}, directory)
            except ValueError:
                pass
            else:
                raise AssertionError("accepted unsafe input path")

        addon = addon_utils.enable("farm_worker", default_set=False)
        assert addon is farm_worker and farm_worker.worker
        stack.callback(addon_utils.disable, "farm_worker")
        assert bpy.app.timers.is_registered(farm_worker.worker.timer)
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 1
        scene.cycles.use_denoising = False
        scene.render.resolution_x = scene.render.resolution_y = 16
        scene.render.resolution_percentage = 100
        target = directory / "render.png"

        def drive():
            # An unauthenticated standard MCP command must never reach bpy.
            with connect() as sock:
                sock.sendall(b'{"type":"execute_code","params":{"code":"bpy.context.scene.name = \'bad\'"}}')
                assert protocol.read_json(sock)["status"] == "error"
            with connect() as sock:
                cmd = {"type": "execute_code", "params": {"code": "bpy.context.scene.name = 'bad'"}}
                try:
                    protocol.call(sock, b"incorrect", cmd)
                except ValueError as ex:
                    assert "authentication" in str(ex)
                else:
                    raise AssertionError("incorrect token accepted")

            # Send the stock client's raw JSON with a deliberately split write,
            # through the same local adapter used by the command-line bridge.
            with connect() as sock:
                sock.sendall(protocol.encode({"type": "farm_challenge"}))
                nonce = protocol.read_json(sock)["nonce"]
                packet = {"type": "get_scene_info", "params": {}}
                packet["mac"] = protocol.signature(token.encode(), nonce, b"request", packet)
                for expected in ("success", "error"):
                    sock.sendall(protocol.encode(packet))
                    assert protocol.read_json(sock)["status"] == expected

            local, bridge_socket = socket.socketpair()

            def bridge():
                with bridge_socket:
                    farm_worker_client.forward(bridge_socket, connect, token.encode())

            threading.Thread(target=bridge, daemon=True).start()
            with local as sock:
                sock.settimeout(30)

                def call(kind, **params):
                    raw = json.dumps({"type": kind, "params": params}).encode()
                    sock.sendall(raw[:3])
                    sock.sendall(raw[3:])
                    reply = protocol.read_json(sock)
                    assert reply["status"] == "success", reply
                    return reply["result"]

                assert call("get_scene_info")["name"] == "Scene"
                assert call("get_object_info", name="Cube")["type"] == "MESH"
                code = ("import threading\nassert threading.current_thread() is threading.main_thread()\n"
                        "bpy.data.objects['Cube'].location.x = 3\nprint('worked')")
                assert "worked" in call("execute_code", code=code)["result"]
                assert call("get_object_info", name="Cube")["location"][0] == 3
                assert call("render", filepath=str(target))["filepath"] == str(target)
                assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            deadline = time.monotonic() + 30
            while len(pulls) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            assert completed == [{"status": "success"}], completed
            assert uploads == {"answer.txt": [b"input:Scene"] * 2}, uploads
            assert len(pulls) >= 2, pulls

        # Background Blender returns after --python. Pump its actual native timer
        # scheduler on this thread while a separate client waits for responses.
        run_timers = getattr(ctypes.CDLL(None), "_ZN7blender17BLI_timer_executeEv")
        run_timers.argtypes = []
        run_timers.restype = None
        with concurrent.futures.ThreadPoolExecutor(1) as executor:
            checks = executor.submit(drive)
            deadline = time.monotonic() + 90
            while not checks.done() and time.monotonic() < deadline:
                run_timers()
                time.sleep(0.005)
            checks.result(timeout=1)
    assert farm_worker.worker is None
    print(f"PASS Blender {bpy.app.version_string} ({'socketpair' if pairs else 'TCP loopback'}): "
          "authentication and replay, four MCP commands, PNG, HTTPS piece, upload retry, next poll, shutdown")


def main():
    import subprocess
    if "--background" in sys.argv:
        exercise(Path(os.environ["BLENDER_USER_CONFIG"]).parent, "--socketpair" in sys.argv)
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", default=BLENDER)
    parser.add_argument("--socketpair", action="store_true", help="Use connected local sockets on restricted hosts")
    args = parser.parse_args()
    tmp = ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp) as name:
        # Ephemeral certificate for the local fixture, including hostname verification.
        config = Path(name) / "tls.cnf"
        config.write_text(
            "[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n[dn]\nCN=Farm fixture\n"
            "[ext]\nsubjectAltName=IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\n"
            "keyUsage=critical,keyCertSign,digitalSignature,keyEncipherment\n"
            "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n"
        )
        subprocess.run(["/usr/bin/openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
                        "-days", "1", "-config", str(config), "-keyout", name + "/farm.key",
                        "-out", name + "/farm.pem"], check=True, capture_output=True)
        env = dict(os.environ, BLENDER_USER_CONFIG=name + "/config", TMPDIR=name,
                   BLENDER_USER_RESOURCES=name + "/resources", PYTHONDONTWRITEBYTECODE="1")
        cmd = [args.blender, "--background", "--factory-startup", "-noaudio", "--python-exit-code", "1",
               "--python", str(Path(__file__).resolve()), "--"]
        if args.socketpair:
            cmd.append("--socketpair")
        subprocess.run(cmd, env=env, check=True, timeout=120)


if __name__ == "__main__":
    main()
