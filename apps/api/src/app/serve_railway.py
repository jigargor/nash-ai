"""HTTP server entrypoint for Railway and similar hosts.

Railway sets ``PORT`` at runtime. Some deploy runners invoke ``startCommand`` without
a shell, so ``--port $PORT`` is never expanded and uvicorn fails to bind — the edge
then returns 502 with ``connection refused``. Reading ``PORT`` in Python avoids that.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    main()
