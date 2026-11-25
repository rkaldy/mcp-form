import logging

from pydantic import JsonValue

logger = logging.getLogger(__name__)


class ProcessingService:
    async def process(self, data: JsonValue):
        """Placeholder processing; log the complete JSON parameter as requested."""
        logger.info("Processing form: %s", data)
