"""Application entry point."""

from __future__ import annotations

import asyncio

from app.runtime.bootstrap import start


def run() -> None:
    asyncio.run(start())


if __name__ == "__main__":
    run()
