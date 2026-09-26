import { ApiError } from '@/lib/api/errors';

/** A failed AI request as one readable sentence (never gateway text: the server sends only a
 * failure kind). */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.problem.code === 'ai_unavailable') return 'Mo is unavailable right now. Try again shortly.';
    return e.problem.detail ?? e.problem.title ?? 'Something went wrong.';
  }
  return 'Something went wrong.';
}
