# SPDX-License-Identifier: GPL-2.0-or-later
"""The Blender MCP JSON stream and its per-command LAN authentication."""

import hashlib
import hmac
import json
import secrets
import time

MAX_MESSAGE = 4 * 1024 * 1024


def encode(message):
    return json.dumps(message, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def read_json(sock):
    # Blender MCP sends one complete object and waits for its reply. It does
    # not append a newline or a length. A recv() can split anywhere in UTF-8.
    data = bytearray()
    # A legitimate render may run for minutes before the first response byte.
    deadline = None
    while len(data) <= MAX_MESSAGE and (deadline is None or time.monotonic() < deadline):
        block = sock.recv(65536)
        if not block:
            raise EOFError
        if deadline is None:
            deadline = time.monotonic() + 30
        data.extend(block)
        if len(data) > MAX_MESSAGE:
            break
        if not data.rstrip().endswith(b"}"):
            continue
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value
    raise ValueError("incomplete or oversized JSON message")


def signature(key, nonce, direction, message):
    packet = b"blender-farm-v1\0" + direction + bytes.fromhex(nonce) + encode(message)
    return hmac.new(key, packet, hashlib.sha256).hexdigest()


def serve(sock, key, dispatch):
    nonce = None
    while True:
        command = read_json(sock)
        if command == {"type": "farm_challenge"}:
            nonce = secrets.token_hex(32)
            sock.sendall(encode({"nonce": nonce}))
            continue
        proof = command.pop("mac", None)
        if not (nonce and isinstance(proof, str) and proof.isascii() and
                hmac.compare_digest(proof, signature(key, nonce, b"request", command))):
            sock.sendall(encode({"status": "error", "message": "authentication required"}))
            return
        try:
            reply = {"status": "success", "result": dispatch(command)}
            if len(encode(reply)) > MAX_MESSAGE - 128:
                raise ValueError("response exceeds message limit")
        except Exception as ex:
            reply = {"status": "error", "message": str(ex)}
        reply["mac"] = signature(key, nonce, b"reply", reply)
        nonce = None
        sock.sendall(encode(reply))


def call(sock, key, command):
    sock.sendall(encode({"type": "farm_challenge"}))
    nonce = read_json(sock)["nonce"]
    if not isinstance(nonce, str) or len(nonce) != 64:
        raise ValueError("invalid worker challenge")
    packet = dict(command)
    packet["mac"] = signature(key, nonce, b"request", command)
    sock.sendall(encode(packet))
    reply = read_json(sock)
    proof = reply.pop("mac", "")
    if not hmac.compare_digest(proof, signature(key, nonce, b"reply", reply)):
        raise ValueError("worker authentication failed")
    return reply
