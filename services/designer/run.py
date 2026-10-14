import asyncio
import sys
import uvicorn

from app.core.config import get_settings


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    settings = get_settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.backend_port)
