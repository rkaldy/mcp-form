from fastapi import Request

from form.service.image import ImageService


def get_image_service(request: Request) -> ImageService:
    """Use the local or hosted R2 bucket selected by Wrangler."""
    env = request.scope.get("env")
    if env is None:
        raise RuntimeError("R2 requires the Workers runtime; start with pywrangler dev")
    return ImageService(env.FORM_IMAGES)
