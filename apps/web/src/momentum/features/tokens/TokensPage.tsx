import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useCreateToken, useMyTokens, useRevokeToken, type ApiToken } from './queries';

const SCOPES: { scope: string; label: string }[] = [
  { scope: 'read', label: 'Read everything I can see' },
  { scope: 'tasks:write', label: 'Create and change tasks, projects and comments' },
  { scope: 'attachments:write', label: 'Upload files' },
  { scope: 'ai', label: 'Use Mo and run agents' },
];

/** S5.1.6 `/settings/tokens`: personal API tokens for scripts. A token can do only what I can,
 * narrowed by its scopes; its secret is shown once, right after creating it. */
export function TokensPage() {
  const tokens = useMyTokens();
  const create = useCreateToken();
  const revoke = useRevokeToken();
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(['read']);
  const [days, setDays] = useState(90);
  const [secret, setSecret] = useState<string | null>(null);

  const toggle = (scope: string) =>
    setScopes((s) => (s.includes(scope) ? s.filter((x) => x !== scope) : [...s, scope]));

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-8">
      <h1 className="page-title flex items-center gap-2">
        <Icon icon={KeyRound} size={20} /> API tokens
      </h1>
      <p className="text-sm text-ink-2">
        Scripts send a token as <code className="font-mono text-xs">Authorization: Bearer …</code>. A token
        acts as you, only for what its scopes allow.
      </p>

      {secret ? (
        <section
          role="status"
          aria-label="New token"
          className="flex flex-col gap-2 rounded-lg border border-ok/40 bg-ok-tint p-3 text-sm"
        >
          <p className="font-medium">Copy your new token now. You won’t see it again.</p>
          <code className="break-all rounded bg-surface px-2 py-1 font-mono text-xs">{secret}</code>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                void navigator.clipboard?.writeText(secret);
                toast.success('Copied');
              }}
            >
              Copy
            </Button>
            <Button size="sm" variant="text" onClick={() => setSecret(null)}>
              Done
            </Button>
          </div>
        </section>
      ) : null}

      <form
        aria-label="Create a token"
        className="flex flex-col gap-3 rounded-lg border border-hairline p-4 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { name: name.trim(), scopes, expires_in_days: days },
            {
              onSuccess: (res) => {
                setSecret(res.secret);
                setName('');
              },
            },
          );
        }}
      >
        <label className="flex flex-col gap-1">
          Name
          <input
            className="rounded-md border border-hairline bg-surface px-2 py-1"
            placeholder="e.g. Nightly ERP sync"
            value={name}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <fieldset className="flex flex-col gap-1">
          <legend className="mb-1">Scopes</legend>
          {SCOPES.map((s) => (
            <label key={s.scope} className="flex items-center gap-2">
              <input type="checkbox" checked={scopes.includes(s.scope)} onChange={() => toggle(s.scope)} />
              {s.label}
            </label>
          ))}
        </fieldset>
        <label className="flex items-center gap-2">
          Expires after
          <select
            className="rounded-md border border-hairline bg-surface px-2 py-1"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>1 year</option>
          </select>
        </label>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          className="w-fit"
          loading={create.isPending}
          disabled={!name.trim() || !scopes.length}
        >
          Create token
        </Button>
      </form>

      <section aria-label="My tokens" className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">My tokens</h2>
        {tokens.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : tokens.isError ? (
          <ErrorState error={tokens.error} onRetry={() => void tokens.refetch()} />
        ) : tokens.data.length ? (
          <ul className="flex flex-col">
            {tokens.data.map((t) => (
              <TokenRow key={t.id} token={t} onRevoke={() => revoke.mutate(t.id)} />
            ))}
          </ul>
        ) : (
          <EmptyState icon={KeyRound} title="No tokens yet" />
        )}
      </section>
    </div>
  );
}

function state(t: ApiToken): string {
  if (t.revoked_at) return 'Revoked';
  if (t.expires_at && new Date(t.expires_at) < new Date()) return 'Expired';
  return t.expires_at ? `Expires ${new Date(t.expires_at).toLocaleDateString()}` : 'No expiry';
}

function TokenRow({ token, onRevoke }: { token: ApiToken; onRevoke: () => void }) {
  const live = !token.revoked_at && (!token.expires_at || new Date(token.expires_at) > new Date());
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hair-soft py-2 text-sm last:border-0">
      <span className="font-medium">{token.name}</span>
      <code className="font-mono text-xs text-muted">{token.prefix}…</code>
      <span className="text-xs text-muted">{token.scopes.join(', ')}</span>
      <span className="text-xs text-muted-2">
        {state(token)} · last used{' '}
        {token.last_used_at ? new Date(token.last_used_at).toLocaleString() : 'never'}
      </span>
      {live ? (
        <Button size="sm" variant="text" className="ml-auto text-crit" onClick={onRevoke}>
          Revoke
        </Button>
      ) : null}
    </li>
  );
}
