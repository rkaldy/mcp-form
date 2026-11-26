// FastAPI's built-in errors and the application's handlers currently use "detail".
export async function readApiError(response, fallback) {
  const payload = await response.json().catch(() => null);
  const details = payload?.details ?? payload?.detail;
  return {
    error: typeof payload?.error === 'string' && payload.error ? payload.error : fallback,
    details: details == null ? '' : typeof details === 'string' ? details : JSON.stringify(details, null, 2),
  };
}
