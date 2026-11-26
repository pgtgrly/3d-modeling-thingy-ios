# SPDX-License-Identifier: GPL-2.0-or-later
"""Farm HTTP and filesystem operations. This module never imports bpy."""

import base64
import functools
import http.client
import json
from pathlib import Path
import re
import ssl
import stat
import tempfile
from urllib.parse import quote, urlsplit

MAX_PIECE = 64 * 1024 * 1024


class Farm:
    def __init__(self, url, token, ca_file=None):
        self.url = urlsplit(url)
        if not self.url.hostname or self.url.username is not None or self.url.query or self.url.fragment:
            raise ValueError("expected an absolute farm base URL without credentials, query or fragment")
        if self.url.scheme == "https":
            context = ssl.create_default_context(cafile=ca_file)
            self.connect = functools.partial(http.client.HTTPSConnection, context=context)
        elif self.url.scheme == "http" and self.url.hostname in {"127.0.0.1", "::1"}:
            self.connect = http.client.HTTPConnection
        else:
            raise ValueError("farm connections require HTTPS (HTTP is available on loopback)")
        self.port = self.url.port
        self.base = self.url.path.rstrip("/") + "/" + quote(token, safe="")

    def request(self, method, path, data=None, headers=None):
        # Direct connections only. A redirect must never forward the token.
        conn = self.connect(self.url.hostname, self.port, timeout=30)
        try:
            conn.request(method, self.base + path, body=data, headers=headers or {})
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                message = f"farm returned HTTP {response.status} for {method}"
                if method == "PUT" and 400 <= response.status < 500 and response.status not in {408, 425, 429}:
                    raise ValueError(message)
                raise OSError(message)
            if method == "GET" and response.status != 204:
                payload = response.read(MAX_PIECE + 1)
                if len(payload) > MAX_PIECE:
                    raise ValueError("farm piece exceeds 64 MiB")
                return json.loads(payload)
            return None
        finally:
            conn.close()

    @staticmethod
    def prepare(piece, inputs):
        files = piece.get("files", {})
        if not isinstance(files, dict):
            raise ValueError("files must map relative paths to base64 data")
        for name, encoded in files.items():
            if not name or any(part in {"", ".", ".."} for part in name.split("/")) or "\\" in name:
                raise ValueError("invalid input path")
            path = inputs / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(base64.b64decode(encoded, validate=True))

    def retry(self, stop, action):
        delay = 1
        while not stop.is_set():
            try:
                action()
                return
            except (OSError, http.client.HTTPException) as ex:
                print(f"Farm worker transfer pending ({type(ex).__name__})", flush=True)
                stop.wait(delay)
                delay = min(30, delay * 2)

    def process(self, piece, dispatch, stop):
        identifier = piece["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
            raise ValueError("invalid piece id")
        path = "/pieces/" + identifier
        with tempfile.TemporaryDirectory(prefix="blender-piece-") as workspace:
            inputs = Path(workspace).resolve() / "inputs"
            outputs = Path(workspace).resolve() / "outputs"
            inputs.mkdir()
            outputs.mkdir()
            try:
                self.prepare(piece, inputs)
                dispatch(piece["script"], inputs, outputs)
                for file in sorted(outputs.rglob("*")):
                    if stop.is_set():
                        return
                    attrs = file.lstat()
                    if stat.S_ISDIR(attrs.st_mode):
                        continue
                    if (not stat.S_ISREG(attrs.st_mode) or attrs.st_nlink != 1 or
                            file.resolve() != file or not file.is_relative_to(outputs)):
                        raise ValueError("output must be a regular file inside outputs")
                    remote = path + "/files/" + quote(file.relative_to(outputs).as_posix())

                    with file.open("rb") as stream:
                        headers = {"Content-Type": "application/octet-stream", "Content-Length": str(attrs.st_size)}

                        def upload():
                            stream.seek(0)
                            self.request("PUT", remote, stream, headers)

                        self.retry(stop, upload)
                result = {"status": "success"}
            except Exception as ex:
                result = {"status": "error", "message": str(ex)}
            self.retry(stop, lambda: self.request("POST", path + "/complete", json.dumps(result).encode(),
                                                 {"Content-Type": "application/json"}))

    def run(self, dispatch, stop):
        delay = 1
        while not stop.is_set():
            try:
                piece = self.request("GET", "/next?runtime=blender")
                if piece is None:
                    stop.wait(1)
                else:
                    self.process(piece, dispatch, stop)
                delay = 1
            except (KeyError, ValueError, TypeError, OSError, http.client.HTTPException) as ex:
                # Exception text from HTTP libraries may contain the token-bearing URL.
                print(f"Farm poll failed ({type(ex).__name__})", flush=True)
                stop.wait(delay)
                delay = min(30, delay * 2)
