# SPDX-License-Identifier: GPL-2.0-or-later

bl_info = {
    "name": "Farm Worker",
    "author": "Blender Authors",
    "version": (1, 0, 0),
    "blender": (5, 3, 0),
    "description": "Run authenticated Blender commands and farm pieces",
    "category": "System",
}

import atexit
from concurrent.futures import Future
import functools
import json
from pathlib import Path
import queue
import socket
import sys
import threading

import bpy

from . import commands, protocol
from .jobs import Farm

worker = None


def documents_directory():
    return Path.home() / "Documents"


def configuration(documents, args):
    path = documents / "farm.json"
    options = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(options, dict):
        raise ValueError("farm.json must contain an object")
    # Only our switches are interpreted. Other arguments belong to Blender or another script.
    args = iter(args)
    for arg in args:
        if arg == "--farm-worker":
            options["server_url"] = next(args, None)
            options["token_file"] = next(args, None)
            if not options["server_url"] or not options["token_file"]:
                raise ValueError("--farm-worker requires a server URL and token file")
        elif arg == "--mcp-port":
            port = next(args, None)
            if not port or not port.isascii() or not port.isdecimal():
                raise ValueError("--mcp-port requires a port number")
            options["mcp_port"] = int(port)
    if not options and not path.exists():
        return None
    options.setdefault("mcp_port", 9876)
    if type(options["mcp_port"]) is not int or not 1 <= options["mcp_port"] <= 65535:
        raise ValueError("mcp_port must be an integer between 1 and 65535")
    if not all(isinstance(options.get(key), str) and options[key] for key in ("server_url", "token_file")):
        raise ValueError("farm configuration requires server_url and token_file")
    return options


class Worker:
    def __init__(self, options, documents):
        self.key = (documents / options["token_file"]).read_bytes().strip()
        if not self.key or len(self.key) > 4096 or self.key in {b".", b".."}:
            raise ValueError("invalid farm token file")
        ca_file = documents / options["ca_file"] if options.get("ca_file") else None
        self.farm = Farm(options["server_url"], self.key.decode("utf-8"), ca_file)
        self.port = options["mcp_port"]
        self.stopped = threading.Event()
        self.pending = queue.Queue(maxsize=16)
        self.active = None
        self.listener = None
        self.slots = threading.BoundedSemaphore(8)
        self.peers = set()
        self.lock = threading.Lock()
        # Blender uses callable identity to unregister a timer.
        self.timer = self.tick

    def start(self):
        if socket.has_dualstack_ipv6():
            self.listener = socket.create_server(("::", self.port), family=socket.AF_INET6,
                                                 dualstack_ipv6=True, backlog=8)
        else:
            self.listener = socket.create_server(("0.0.0.0", self.port), backlog=8)
        self.listener.settimeout(0.5)
        bpy.app.timers.register(self.timer, persistent=True)
        threading.Thread(target=self.accept, name="Blender MCP listener", daemon=True).start()
        threading.Thread(target=self.farm.run, args=(self.piece, self.stopped), name="Blender farm", daemon=True).start()

    def submit(self, make_steps):
        future = Future()
        try:
            self.pending.put_nowait((make_steps, future))
        except queue.Full:
            raise RuntimeError("worker command queue is full") from None
        while not self.stopped.is_set():
            try:
                return future.result(timeout=0.25)
            except TimeoutError:
                if future.done():
                    return future.result()
        raise RuntimeError("worker stopped")

    def piece(self, script, inputs, outputs):
        return self.submit(functools.partial(commands.execute, script, inputs, outputs))

    def tick(self):
        if self.stopped.is_set():
            return None
        if self.active is None:
            try:
                make_steps, future = self.pending.get_nowait()
            except queue.Empty:
                return 0.05
            self.active = (make_steps(), future)
        steps, future = self.active
        try:
            next(steps)
        except StopIteration as done:
            future.set_result(done.value)
            self.active = None
        except BaseException as ex:
            # A failed job (including SystemExit) must not unregister the timer.
            future.set_exception(RuntimeError(str(ex)))
            self.active = None
        return 0.01

    def accept(self):
        while not self.stopped.is_set():
            try:
                sock, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self.lock:
                if self.stopped.is_set() or not self.slots.acquire(blocking=False):
                    sock.close()
                    continue
                self.peers.add(sock)
            threading.Thread(target=self.client, args=(sock,), name="Blender MCP client", daemon=True).start()

    def client(self, sock):
        try:
            with sock:
                sock.settimeout(30)
                protocol.serve(sock, self.key, lambda cmd: self.submit(functools.partial(commands.command, cmd)))
        except (EOFError, OSError, ValueError, RecursionError):
            pass
        finally:
            with self.lock:
                self.peers.discard(sock)
            self.slots.release()

    def close(self):
        self.stopped.set()
        if self.listener:
            self.listener.close()
        with self.lock:
            for sock in self.peers:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if bpy.app.timers.is_registered(self.timer):
            bpy.app.timers.unregister(self.timer)
        if self.active:
            self.active[0].close()
            self.active = None


def set_awake(active):
    if sys.platform == "ios":
        import _bpy
        _bpy._ios_farm_set_active(active)


def register():
    global worker
    if worker is not None:
        return
    documents = documents_directory()
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = configuration(documents, args)
    if options is None:
        return
    candidate = Worker(options, documents)
    try:
        candidate.start()
        set_awake(True)
    except Exception:
        candidate.close()
        raise
    worker = candidate
    print(f"Farm worker listening on TCP port {worker.port}", flush=True)
    atexit.register(unregister)


def unregister():
    global worker
    if worker is not None:
        atexit.unregister(unregister)
        try:
            worker.close()
        finally:
            set_awake(False)
            worker = None
