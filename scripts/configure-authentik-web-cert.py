#!/usr/bin/env python3
"""Create and assign an Authentik HTTPS certificate for the homelab domain."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path


def clean_env_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value[0] in "\"'":
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end != -1 else value[1:]
    return value.split(" #", 1)[0].strip()


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = clean_env_value(value)
    return values


def request(method: str, base_url: str, token: str, path: str, body: object | None = None) -> object:
    payload = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{base_url}/api/v3{path}", data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"ERROR: {method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"ERROR: {method} {path} failed: {exc.reason}") from exc


def first_by_name(base_url: str, token: str, name: str) -> dict[str, object] | None:
    query = urllib.parse.urlencode({"search": name})
    data = request("GET", base_url, token, f"/crypto/certificatekeypairs/?{query}")
    for item in data.get("results", []):
        if item.get("name") == name:
            return item
    return None


def default_brand(base_url: str, token: str) -> dict[str, object]:
    data = request("GET", base_url, token, "/core/brands/")
    for item in data.get("results", []):
        if item.get("default"):
            return item
    results = data.get("results", [])
    if results:
        return results[0]
    raise SystemExit("ERROR: no Authentik Brand was found")


def generate_cert(domain: str, cert_path: Path, key_path: Path) -> None:
    san = ",".join(
        [
            f"DNS:{domain}",
            "DNS:kadin-main-sys",
            "DNS:authentik",
            "DNS:authentik_server",
            "IP:127.0.0.1",
        ]
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "825",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={domain}",
            "-addext",
            f"subjectAltName={san}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Authentik's HTTPS cert for Immich OIDC")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--out-cert", default=None)
    args = parser.parse_args()

    env = load_env(Path(args.env_file))
    domain = env["DOMAIN"]
    base_url = env["AUTHENTIK_URL"].rstrip("/")
    token = env["AUTHENTIK_API_TOKEN"]
    name = f"homelab {domain} web certificate"

    with tempfile.TemporaryDirectory(prefix="authentik-web-cert-") as tmp:
        cert_path = Path(tmp) / "cert.pem"
        key_path = Path(tmp) / "key.pem"
        generate_cert(domain, cert_path, key_path)

        body = {
            "name": name,
            "certificate_data": cert_path.read_text(encoding="utf-8"),
            "key_data": key_path.read_text(encoding="utf-8"),
        }

        existing = first_by_name(base_url, token, name)
        if existing:
            cert_pair = request("PATCH", base_url, token, f"/crypto/certificatekeypairs/{existing['pk']}/", body)
            print(f"Updated certificate-keypair: {name}")
        else:
            cert_pair = request("POST", base_url, token, "/crypto/certificatekeypairs/", body)
            print(f"Created certificate-keypair: {name}")

        brand = default_brand(base_url, token)
        brand_uuid = brand["brand_uuid"]
        request("PATCH", base_url, token, f"/core/brands/{brand_uuid}/", {"web_certificate": cert_pair["pk"]})
        print(f"Assigned certificate to Brand: {brand.get('domain')}")

        if args.out_cert:
            Path(args.out_cert).write_text(body["certificate_data"], encoding="utf-8")
            print(f"Wrote public certificate: {args.out_cert}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
