from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from form.api.models import ErrorResult, ScanResult
from form.api.stream import StreamServer
from form.exceptions import FatalError, UserInputError
from form.model.session import SessionStatus


@pytest.mark.anyio
async def test_stream_yields_messages_lazily_in_order():
    """Emit one NDJSON message per chunk and advance the generator only on demand."""
    session_id = uuid4()
    messages = [
        ScanResult(session_id=None, status=SessionStatus.NORMALIZING),
        ScanResult(session_id=session_id, status=SessionStatus.SCANNING),
    ]
    emitted = []

    async def generator() -> AsyncIterator[ScanResult | ErrorResult]:
        for message in messages:
            emitted.append(message)
            yield message

    response = StreamServer(generator)
    stream = aiter(response.body_iterator)
    assert emitted == []
    for index, message in enumerate(messages):
        chunk = await anext(stream)
        assert chunk == message.model_dump_json() + "\n"
        assert emitted == messages[: index + 1]
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.anyio
@pytest.mark.parametrize("error_type", [UserInputError, FatalError])
@pytest.mark.parametrize("after_progress", [False, True])
async def test_stream_converts_generator_errors_to_terminal_message(
    error_type: type[UserInputError | FatalError], after_progress: bool
):
    """Catch errors during iteration, retain preceding progress and emit the cause and severity."""
    progress = ScanResult(session_id=None, status=SessionStatus.NORMALIZING)

    async def generator() -> AsyncIterator[ScanResult | ErrorResult]:
        if after_progress:
            yield progress
        raise error_type("Testovací chyba") from RuntimeError("Testovací příčina")

    adapter = TypeAdapter(ScanResult | ErrorResult)
    messages = []
    async for chunk in StreamServer(generator).body_iterator:
        assert isinstance(chunk, str) and chunk.endswith("\n")
        messages.append(adapter.validate_json(chunk))
    assert messages == ([progress] if after_progress else []) + [
        ErrorResult(
            error="Testovací chyba",
            error_details="Testovací příčina",
            fatal=error_type is FatalError,
        )
    ]
