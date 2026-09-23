/** RFC 9457 problem+json returned by the Momentum API. */
export interface Problem {
  type?: string;
  title?: string;
  status: number;
  code: string;
  detail?: string;
  request_id?: string | null;
  login_url?: string;
  errors?: { field: string; message: string }[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title ?? problem.code);
    this.name = 'ApiError';
    this.status = problem.status;
    this.code = problem.code;
    this.problem = problem;
  }

  get fieldErrors(): Record<string, string> {
    return Object.fromEntries((this.problem.errors ?? []).map((e) => [e.field, e.message]));
  }
}

export function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === 'object' && 'code' in body) {
    return new ApiError({ status, ...(body as Omit<Problem, 'status'>) });
  }
  return new ApiError({
    status,
    code: status >= 500 ? 'internal_error' : 'http_error',
    title: `HTTP ${status}`,
  });
}

export function isUnauthenticated(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 401;
}
