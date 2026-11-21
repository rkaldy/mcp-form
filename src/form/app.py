from fastapi import FastAPI

app = FastAPI(title="Form Scanner")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Form Scanner"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
