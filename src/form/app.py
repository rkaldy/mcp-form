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
async def user_input_error(request: Request, error: UserInputError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.exception_handler(ScanError)
async def scan_error(request: Request, error: ScanError) -> JSONResponse:
    logging.getLogger(__name__).error(
        "Form request failed", extra={"error_type": type(error.__cause__).__name__}
    )
    return JSONResponse(status_code=500, content={"detail": "Form processing failed"})


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
