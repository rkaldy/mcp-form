import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from form.api.scans import router
from form.exceptions import ScanError, UserInputError
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


@app.exception_handler(UserInputError)
async def user_input_error(_request: Request, error: UserInputError) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": str(error), "detail": str(error.__cause__)}
    )


@app.exception_handler(ScanError)
async def scan_error(_request: Request, error: ScanError) -> JSONResponse:
    logger.error(f"{error}: {error.__cause__}")
    return JSONResponse(
        status_code=500, content={"error": str(error), "detail": str(error.__cause__)}
    )


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
