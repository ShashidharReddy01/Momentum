import { useNavigate, useSearchParams } from 'react-router';
import { ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMomentumConfig } from '@/lib/config';
import { useDevLogin, useDevUsers } from './queries';

/** Local development login (AUTH_MODE=dev or easyauth-sim). Never available in production. */
export function DevLoginPage() {
  const config = useMomentumConfig();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const users = useDevUsers(config.auth.dev_login);
  const login = useDevLogin();

  if (!config.auth.dev_login) return <p className="p-8">Dev login is disabled.</p>;

  const returnTo = params.get('return_to') ?? `${config.base_path}/`;
  const target = returnTo.startsWith(config.base_path) ? returnTo.slice(config.base_path.length) || '/' : '/';

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-4 py-10">
      <header className="flex flex-col gap-2">
        <span className="w-fit rounded-sm border border-mock px-1.5 font-mono text-[10px] uppercase tracking-wider text-mock">
          Dev login · {config.auth.mode}
        </span>
        <h1 className="font-serif text-3xl">Momentum</h1>
        <p className="text-sm text-muted">
          Pick a seeded user. In production, Easy Auth (Entra ID) signs people in.
        </p>
      </header>
      {users.isPending ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-11" />
          ))}
        </div>
      ) : users.isError ? (
        <ErrorState error={users.error} onRetry={() => void users.refetch()} />
      ) : users.data.length === 0 ? (
        <p className="text-sm text-muted">
          No users yet. Run <code className="font-mono">make seed</code>.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-hair-soft overflow-hidden rounded-lg border border-hairline bg-paper">
          {users.data.map((u) => (
            <li key={u.id}>
              <button
                type="button"
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-paper-2 disabled:opacity-50"
                disabled={login.isPending}
                onClick={() => login.mutate(u.id, { onSuccess: () => navigate(target, { replace: true }) })}
              >
                <Avatar name={u.name} size={28} />
                <span className="flex-1">
                  <span className="block text-sm font-medium">{u.name}</span>
                  <span className="block text-xs text-muted">{u.email}</span>
                </span>
                <span className="eyebrow">{u.role}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
