"""AgentSentry AI backend entrypoint.

Run with:  python main.py
"""
from __future__ import annotations

import uvicorn

from app.factory import create_app
from config import get_settings

app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "development",
    )


if __name__ == "__main__":
    main()
