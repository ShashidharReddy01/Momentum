import { useEffect, useState, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { UNAUTHENTICATED_EVENT } from '@/lib/api/client';
import { isUnauthenticated } from '@/lib/api/errors';
import { useMomentumConfig } from '@/lib/config';
import { useMe } from './queries';

/** Blocks the app until the user is known; redirects to the provider's login when needed. */
export function AuthGate({ children }: { children: ReactNode }) {
  const config = useMomentumConfig();
  const location = useLocation();
  const me = useMe();
  const expired = useSessionExpired();
  const returnTo = `${config.base_path}${location.pathname}${location.search}`;

  if (me.isPending) {
    return (
      <div className="p-8 text-sm text-muted" aria-busy>
        Signing you in…
      </div>
    );
  }
  if (me.isError) {
    if (isUnauthenticated(me.error)) {
      if (config.auth.dev_login) {
        return <Navigate to={`/dev/login?return_to=${encodeURIComponent(returnTo)}`} replace />;
      }
      window.location.assign(me.error.problem.login_url ?? config.auth.login_url);
      return null;
    }
    return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;
  }
  return (
    <>
      {expired ? <SessionExpiredBanner loginUrl={config.auth.login_url} /> : null}
      {children}
    </>
  );
}

function useSessionExpired(): boolean {
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    const on = () => setExpired(true);
    window.addEventListener(UNAUTHENTICATED_EVENT, on);
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, on);
  }, []);
  return expired;
}

function SessionExpiredBanner({ loginUrl }: { loginUrl: string }) {
  return (
    <div
      role="alert"
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-3 bg-warn-tint py-2 text-sm"
    >
      Your session expired. Your unsaved text is kept on this device.
      <Button size="sm" variant="primary" onClick={() => window.location.assign(loginUrl)}>
        Sign in again
      </Button>
    </div>
  );
}
