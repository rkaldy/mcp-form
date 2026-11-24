# Live LLM tests

These two tests each make one paid provider request. They are skipped unless
`RUN_LLM_EXTERNAL_TESTS=1`. They use dedicated credentials from environment
variables and never load the application's `.env`:

- `EXTERNAL_LLM_MODEL`: a model supporting image input and structured outputs.
- `EXTERNAL_LLM_API_KEY`: an API key for a dedicated test account.
- `EXTERNAL_LLM_REASONING_EFFORT`: optional reasoning configuration.

After exporting these variables in your shell, run:

```sh
RUN_LLM_EXTERNAL_TESTS=1 uv run pytest tests/external -q --tb=short
```

The scan test uploads `tests/external/scan.jpg` to the configured provider. Use
synthetic test data in this image. Tests do not log extracted form values, use a
120-second request timeout, and do not retry provider calls. Do not enable SDK
debug logging or pytest `--showlocals`, which could expose request/response data.

The healthcheck uses the minimal prompt `Reply OK.` without a fixed output token
limit, so reasoning models can complete their response. Provider usage and cost
limits should be configured on the dedicated test account.
