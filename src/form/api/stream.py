import logging
from collections.abc import AsyncIterator, Callable

from starlette.responses import StreamingResponse

from form.api.models import ErrorResult, ScanResult
from form.exceptions import FatalError, UserInputError

type StreamingEventGenerator = Callable[[], AsyncIterator[ScanResult | ErrorResult]]

logger = logging.getLogger(__name__)


class StreamServer(StreamingResponse):
    def __init__(self, generator: StreamingEventGenerator):
        super().__init__(
            self.lines(generator),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    async def run(
        generator: StreamingEventGenerator,
    ) -> AsyncIterator[ScanResult | ErrorResult]:
        try:
            async for result in generator():
                yield result
        except (UserInputError, FatalError) as error:
            yield StreamServer.error_result(error)

    @staticmethod
    async def lines(generator: StreamingEventGenerator) -> AsyncIterator[str]:
        async for result in StreamServer.run(generator):
            yield result.model_dump_json() + "\n"

    @staticmethod
    def error_result(error: UserInputError | FatalError) -> ErrorResult:
        fatal = isinstance(error, FatalError)
        logger.log(
            logging.ERROR if fatal else logging.WARNING,
            f"{error}: {error.__cause__}",
            extra={"error_type": type(error).__name__},
        )
        return ErrorResult(
            error=str(error), error_details=str(error.__cause__), fatal=fatal
        )
