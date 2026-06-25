"""Small helper used by run.bat to keep cmd parsing simple."""

from __future__ import annotations

import socket
import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    try:
        port = int(args[0])
    except (IndexError, ValueError):
        return 2

    if not 1 <= port <= 65535:
        return 2

    sock = socket.socket()
    try:
        sock.settimeout(0.2)
        return 1 if sock.connect_ex(("127.0.0.1", port)) == 0 else 0
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
