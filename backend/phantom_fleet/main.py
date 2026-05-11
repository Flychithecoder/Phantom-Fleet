"""
Phantom Fleet — CLI entry point.

Usage:
    # Development (auto-reload):
    uvicorn phantom_fleet.api.app:app --port 8000 --reload

    # Via this module directly:
    python -m phantom_fleet.main

    # Via uvicorn programmatically:
    python -c "from phantom_fleet.main import main; main()"
"""
from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    host = os.getenv("PHANTOM_HOST", "0.0.0.0")
    port = int(os.getenv("PHANTOM_PORT", "8000"))
    reload = os.getenv("PHANTOM_RELOAD", "false").lower() == "true"

    uvicorn.run(
        "phantom_fleet.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
