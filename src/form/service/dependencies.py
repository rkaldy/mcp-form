from typing import Annotated

from fastapi import Depends

from form.database.database import Database, get_database
from form.llm.llm import LLM, get_llm
from form.service.image import ImageService
from form.service.processing import ProcessingService
from form.service.scan import ScanService
from form.service.session import SessionService
from form.settings import Settings, get_settings


def get_session_service(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
) -> SessionService:
    return SessionService(settings, database)


def get_image_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ImageService:
    return ImageService(settings)


def get_scan_service(
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
    llm: Annotated[LLM, Depends(get_llm)],
    images: Annotated[ImageService, Depends(get_image_service)],
) -> ScanService:
    return ScanService(
        settings,
        sessions,
        images,
        llm,
    )


def get_processing_service(
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
) -> ProcessingService:
    return ProcessingService(settings, sessions)
