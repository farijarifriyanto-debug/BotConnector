"""Local/dev runner for the Parking API (VPS smoke runs only; not exposed publicly).

    .venv/bin/python -m parking.api.run   # serves 127.0.0.1:8711/parking/api
"""

from __future__ import annotations

import uvicorn

from parking.api.app import create_app

app = create_app()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8711, log_level="info")


if __name__ == "__main__":
    main()
