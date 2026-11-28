import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from form.api.scan import router
from form.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Use Uvicorn's formatter for application logs during the server lifetime."""
    logger = logging.getLogger("form")
    logger.setLevel(get_settings().log_level.upper())
    if handlers := logging.getLogger("uvicorn").handlers:
        logger.handlers = handlers.copy()
        logger.propagate = False
        yield


app = FastAPI(title="Form Scanner", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount(
    "/",
    StaticFiles(
        directory=Path(__file__).with_name("static"), html=True, check_dir=False
    ),
    name="ui",
)
