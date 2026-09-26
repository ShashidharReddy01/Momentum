import { toApiError } from './api/errors';

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

/**
 * POST a JSON body and read a server-sent-event stream (api-conventions §8), calling `onEvent`
 * for each event as it arrives. Non-2xx responses throw an `ApiError` like the API client does.
 * Pass an `AbortSignal` to stop reading (the server then cancels the run).
 */
export async function postSse(
  url: string,
  body: unknown,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-Requested-With': 'momentum',
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    throw toApiError(res.status, await res.json().catch(() => null));
  }
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf('\n\n');
    while (cut >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const parsed = parseBlock(block);
      if (parsed) onEvent(parsed);
      cut = buffer.indexOf('\n\n');
    }
  }
  const tail = parseBlock(buffer);
  if (tail) onEvent(tail);
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join('\n')) as Record<string, unknown> };
  } catch {
    return null;
  }
}
