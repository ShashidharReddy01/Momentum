import { describe, expect, it } from 'vitest';
import { ApiError, isUnauthenticated, toApiError } from './errors';

describe('toApiError', () => {
  it('parses problem+json bodies', () => {
    const err = toApiError(422, {
      code: 'validation_failed',
      detail: 'Invalid request',
      errors: [{ field: 'title', message: 'too long' }],
    });
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('validation_failed');
    expect(err.fieldErrors).toEqual({ title: 'too long' });
  });
  it('falls back for non-problem bodies', () => {
    expect(toApiError(502, 'bad gateway').code).toBe('internal_error');
  });
  it('detects unauthenticated', () => {
    expect(isUnauthenticated(toApiError(401, { code: 'unauthenticated' }))).toBe(true);
  });
});
