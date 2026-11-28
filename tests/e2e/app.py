"""Serve the actual UI and API routes with isolated, deterministic service doubles."""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import SecretStr

from form.api.scan import router
from form.exceptions import FatalError, UserInputError
from form.llm.model import BoundingBox, Coord, FieldType
from form.model.session import ReviewRequest, ToReview
from form.service.dependencies import get_processing_service, get_scan_service
from form.service.image import ImageService
from form.settings import Settings, get_settings

settings = Settings(
    _env_file=None,
    target_spreadsheet="https://docs.google.com/spreadsheets/d/synthetic-test",
    llm_model="test",
    llm_api_key=SecretStr("synthetic-test-key"),
)
app = FastAPI()
app.include_router(router)


class Scenario:
    def __init__(self, session_id: UUID, mode: str, paused: bool):
        self.session_id = session_id
        self.mode = mode
        self.paused = paused
        self.image = b""
        self.review: ReviewRequest | None = None
        self.attempts = 0
        self.gates = {
            stage: asyncio.Event() for stage in ("normalize", "scan", "process")
        }

    async def wait(self, stage: str):
        if self.paused:
            await self.gates[stage].wait()
            self.gates[stage].clear()


scenarios: dict[UUID, Scenario] = {}


def scenario(request: Request) -> Scenario:
    session_id = UUID(request.headers["x-test-id"])
    if session_id not in scenarios:
        scenarios[session_id] = Scenario(
            session_id,
            request.headers.get("x-test-scenario", "success"),
            request.headers.get("x-test-paused") == "true",
        )
    return scenarios[session_id]


class ScanDouble:
    def __init__(self, state: Scenario):
        self.state = state

    async def normalize(self, image: bytes) -> UUID:
        self.state.session_id = uuid4()
        await self.state.wait("normalize")
        if self.state.mode == "scan-user-error":
            raise UserInputError("Fotografii nelze přečíst") from ValueError(
                "Vyfoťte ji znovu."
            )
        if self.state.mode == "scan-fatal-error":
            raise FatalError("Skenování selhalo") from RuntimeError(
                "Služba je nedostupná."
            )
        self.state.image = ImageService(settings).normalize(image)
        return self.state.session_id

    async def scan(self, session_id: UUID) -> list[ToReview]:
        assert session_id == self.state.session_id
        await self.state.wait("scan")
        if self.state.mode == "success":
            return []
        box = BoundingBox(top_left=Coord(x=0, y=0), bottom_right=Coord(x=16, y=16))
        return [
            ToReview(
                type=FieldType.DATE,
                path="static_fields.date",
                label="Datum",
                value="2026-11-08",
                bounding_box=box,
            ),
            ToReview(
                type=FieldType.NAME,
                path="table_fields.0.name",
                label="Jméno účastníka",
                value={"first_name": "Jana", "surname": "Testová"},
                bounding_box=box,
            ),
        ]

    async def field_crop(self, session_id: UUID, bounding_box: BoundingBox) -> bytes:
        assert session_id == self.state.session_id
        return ImageService(settings).rotate_crop(self.state.image, 0, bounding_box)

    async def review(self, review: ReviewRequest):
        assert review.session_id == self.state.session_id
        self.state.review = review
        self.state.attempts += 1


class ProcessingDouble:
    def __init__(self, state: Scenario):
        self.state = state

    async def process(self, session_id: UUID):
        assert session_id == self.state.session_id
        await self.state.wait("process")
        if self.state.mode == "review-user-error" and self.state.attempts == 1:
            raise UserInputError("Chybně zadaná hodnota") from ValueError(
                "Zkontrolujte datum."
            )
        if self.state.mode == "review-fatal-error":
            raise FatalError("Zpracování selhalo") from RuntimeError(
                "Tabulka je nedostupná."
            )
        if self.state.mode != "success":
            assert self.state.review is not None
            values = {field.path: field.value for field in self.state.review.reviews}
            if values != {
                "static_fields.date": "2026-11-09",
                "table_fields.0.name": {"first_name": "Eva", "surname": "Ukázková"},
            }:
                raise FatalError("Processing neobdržel opravené hodnoty")


def scan_service(request: Request) -> ScanDouble:
    return ScanDouble(scenario(request))


def processing_service(request: Request) -> ProcessingDouble:
    return ProcessingDouble(scenario(request))


app.dependency_overrides[get_settings] = lambda: settings
app.dependency_overrides[get_scan_service] = scan_service
app.dependency_overrides[get_processing_service] = processing_service


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/__test/release/{stage}")
async def release(stage: str, request: Request):
    scenario(request).gates[stage].set()


@app.delete("/__test/scenario")
async def cleanup(request: Request):
    state = scenarios.pop(UUID(request.headers["x-test-id"]), None)
    if state is not None:
        for gate in state.gates.values():
            gate.set()


app.mount(
    "/", StaticFiles(directory=Path(__file__).parents[2] / "src/form/static", html=True)
)
