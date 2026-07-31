#!/usr/bin/env python3
"""Write a server's presented TLS certificate to a PEM file."""

from __future__ import annotations

import argparse
import ssl
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a presented TLS certificate")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    pem = ssl.get_server_certificate((args.host, args.port))
    Path(args.out).write_text(pem, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
