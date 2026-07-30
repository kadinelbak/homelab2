#!/usr/bin/env python3
import json
import os
import re
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

API_KEY = os.environ.get("WOL_API_KEY", "")
DEFAULT_MAC = os.environ.get("WOL_MAC_ADDRESS", "")
DEFAULT_BROADCAST = os.environ.get("WOL_BROADCAST_ADDRESS", "255.255.255.255")
DEFAULT_PORT = int(os.environ.get("WOL_PORT", "9"))
LISTEN_HOST = os.environ.get("WOL_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("WOL_LISTEN_PORT", "9999"))

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-]?[0-9A-Fa-f]{2}){5}$")


def normalize_mac(mac):
    mac = mac.strip()
    if not MAC_RE.match(mac):
        raise ValueError("invalid MAC address")
    return re.sub(r"[:-]", "", mac).lower()


def magic_packet(mac):
    raw = bytes.fromhex(normalize_mac(mac))
    return b"\xff" * 6 + raw * 16


def send_wol(mac, broadcast, port):
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, int(port)))


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-wol-api/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def write_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if not API_KEY or API_KEY.startswith("CHANGE_ME"):
            return False
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {API_KEY}":
            return True
        parsed = urlparse(self.path)
        query_key = parse_qs(parsed.query).get("token", [""])[0]
        return query_key == API_KEY

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            configured = bool(API_KEY and not API_KEY.startswith("CHANGE_ME") and DEFAULT_MAC)
            self.write_json(HTTPStatus.OK, {"ok": True, "configured": configured})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/wake":
            self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self.authorized():
            self.write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            mac = payload.get("mac") or DEFAULT_MAC
            broadcast = payload.get("broadcast") or DEFAULT_BROADCAST
            port = int(payload.get("port") or DEFAULT_PORT)
            send_wol(mac, broadcast, port)
        except Exception as exc:
            self.write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        self.write_json(HTTPStatus.OK, {"ok": True, "mac": mac, "broadcast": broadcast, "port": port})


def main():
    httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"Listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
