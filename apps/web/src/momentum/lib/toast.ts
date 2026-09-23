import { toast } from 'sonner';
import { ApiError } from './api/errors';

/** Show an API/domain error as a toast with the server's human message. */
export function toastError(err: unknown, fallback = 'Something went wrong'): void {
  if (err instanceof ApiError) {
    if (err.status === 401) return; // handled by the session-expired banner
    toast.error(err.problem.detail ?? err.problem.title ?? fallback);
    return;
  }
  toast.error(fallback);
}
