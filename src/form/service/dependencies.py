from typing import Annotated

from fastapi import Depends, Request

from form.database.d1 import D1Binding
from form.database.dependencies import get_database_binding
from form.llm.llm import LLM
from form.service.image import ImageService
from form.service.processing import ProcessingService
from form.service.scan import ScanService
from form.settings import Settings


def get_settings(request: Request) -> Settings:
    env = request.scope.get("env")
    if env is None:
        return Settings()
    else:
        values = {
            name: getattr(env, name.upper())
            for name in Settings.model_fields
            if hasattr(env, name.upper())
        }
        return Settings(**values)


def get_image_service(request: Request) -> ImageService:
    env = request.scope.get("env")
    if env is None:
        raise RuntimeError("R2 requires the Workers runtime; start with pywrangler dev")
    return ImageService(env.FORM_IMAGES)


def get_scan_service(
    settings: Annotated[Settings, Depends(get_settings)],
    binding: Annotated[D1Binding, Depends(get_database_binding)],
    images: Annotated[ImageService, Depends(get_image_service)],
    processing: Annotated[ProcessingService, Depends(get_processing_service)],
) -> ScanService:
    config: dict[str, str | int] = {"timeout": settings.llm_timeout}
    if settings.llm_reasoning_effort is not None:
        config["reasoning_effort"] = settings.llm_reasoning_effort
    return ScanService(
        binding,
        images,
        LLM(settings.llm_model, settings.llm_api_key.get_secret_value(), config),
        processing,
        settings,
    )


def get_processing_service() -> ProcessingService:
    return ProcessingService()
