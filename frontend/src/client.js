export async function requestTriage(input, fetcher = fetch) {
  let response;
  try {
    response = await fetcher('/triage', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input), signal: AbortSignal.timeout(180000),
    });
  } catch {
    throw new Error('The API could not be reached or took too long. Check that IssueLens is running, then try again.');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : 'The request could not be processed.';
    const help = response.status === 503 || response.status === 504
      ? ' Check the API terminal and confirm Ollama is running with qwen3:4b available.' : '';
    throw new Error(`${detail}${help}`);
  }
  if (!data || !Array.isArray(data.candidates) || !Array.isArray(data.missing_information)) {
    throw new Error('The API returned an unexpected response. Check the API terminal.');
  }
  return data;
}

export function safeIssueUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'github.com' && /^\/[^/]+\/[^/]+\/issues\/\d+$/.test(url.pathname) ? url.href : null;
  } catch { return null; }
}
