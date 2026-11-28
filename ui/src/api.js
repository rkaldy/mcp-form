function apiError(payload, fallback) {
  const details = payload?.error_details ?? payload?.details ?? payload?.detail;
  return {
    error: typeof payload?.error === 'string' && payload.error ? payload.error : fallback,
    details: details == null ? '' : typeof details === 'string' ? details : JSON.stringify(details, null, 2),
  };
}

export async function readApiError(response, fallback) {
  return apiError(await response.json().catch(() => null), fallback);
}

export function streamError(result) {
  return apiError(result, 'Formulář se nepodařilo zpracovat.');
}

// A network chunk can contain part of a JSON line, several lines, or part of a UTF-8 character.
export async function* readScanStream(response) {
  if (!response.body) throw new Error('Response stream is unavailable');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '';
  let terminal = false;

  function message(line) {
    const result = JSON.parse(line);
    if (typeof result?.error === 'string' && typeof result.fatal === 'boolean') {
      terminal = true;
    } else if (['normalizing', 'scanning', 'processing', 'reviewing', 'finished'].includes(result?.status)) {
      if (result.status === 'reviewing' && (!result.session_id || !Array.isArray(result.reviews))) {
        throw new Error('Invalid review response');
      }
      terminal = result.status === 'reviewing' || result.status === 'finished';
    } else {
      throw new Error('Invalid scan response');
    }
    return result;
  }

  try {
    while (!terminal) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let newline;
      while (!terminal && (newline = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) yield message(line);
      }
      if (done) {
        if (!terminal && buffer.trim()) yield message(buffer.trim());
        if (!terminal) throw new Error('Scan stream ended before a result');
        break;
      }
    }
  } finally {
    try {
      // Closing a completed response must not replace its result with a cleanup error.
      await reader.cancel().catch(() => {});
    } finally {
      reader.releaseLock();
    }
  }
}
