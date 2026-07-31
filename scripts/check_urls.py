#!/usr/bin/env python3
"""Check URLs and print compact HTTP results."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Check URLs")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--host-header", help="Optional Host header to send with every request")
    args = parser.parse_args()

    for url in args.urls:
        try:
            request = urllib.request.Request(url)
            if args.host_header:
                request.add_header("Host", args.host_header)
            response = urllib.request.urlopen(request, timeout=args.timeout)
            print(f"{response.status} {url}")
        except urllib.error.HTTPError as exc:
            print(f"{exc.code} {url}")
        except Exception as exc:
            print(f"ERR {url} {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
