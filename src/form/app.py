import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from form.api.scans import router
from form.exceptions import ScanError, UserInputError

app = FastAPI(title="Form Scanner")
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


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Form Scanner"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
