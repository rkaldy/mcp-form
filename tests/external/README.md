# Live LLM tests

These two tests each make one paid provider request. They are skipped unless
`RUN_LLM_EXTERNAL_TESTS=1`. They use the application's current `Settings()`
configuration, including `.env`. Environment variables take precedence over `.env`:

- `LLM_MODEL`: a model supporting image input and structured outputs.
- `LLM_API_KEY`: the configured API key.
- `LLM_REASONING_EFFORT`: optional reasoning configuration.

After configuring these values in `.env` or your environment, run:

```sh
RUN_LLM_EXTERNAL_TESTS=1 uv run pytest tests/external -q --tb=short
```

The scan test uploads `tests/external/scan.jpg` to the configured provider. Use
synthetic test data in this image. Tests do not log extracted form values, use a
120-second request timeout, and do not retry provider calls. Do not enable SDK
debug logging or pytest `--showlocals`, which could expose request/response data.

The healthcheck uses the minimal prompt `Reply OK.` without a fixed output token
limit, so reasoning models can complete their response. Provider usage and cost
limits apply to the configured account.
