import { Archive, Building2, Merge, Search } from 'lucide-react';
import { useDeferredValue, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { skillText, useSkills } from '@/features/agents';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { formatRelative } from '@/lib/dates';
import { humanize } from './model';
import { useEntities, useEntity, useEntityActions, useEntityActivity, useRecords } from './queries';
import { RecordStatus } from './RecordStatus';

/** `/entities` (Phase 7.6 S76-08, spec §12.5): the vendors and other things agents keep track
 * of, searchable, with the type from `?type=`. */
export function EntitiesPage() {
  const [params, setParams] = useSearchParams();
  const type = params.get('type');
  const [q, setQ] = useState('');
  const [archived, setArchived] = useState(false);
  const deferred = useDeferredValue(q.trim());
  const list = useEntities(deferred, type, archived ? 'archived' : 'active');
  const all = useEntities('', null);
  const typeKeys = [...new Set((all.data ?? []).map((e) => e.type))];
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-8">
      <h1 className="page-title">{type ? `${humanize(type)}s` : 'Entities'}</h1>
      <p className="-mt-2 text-sm text-muted">
        The vendors and other parties agents recognise in documents, with the names they go by.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative flex min-w-56 flex-1 items-center">
          <Icon icon={Search} size={14} className="pointer-events-none absolute left-2 text-muted" />
          <span className="sr-only">Search entities</span>
          <input
            type="search"
            placeholder="Search names and aliases…"
            className="h-8 w-full rounded-md border border-hairline bg-surface pr-2 pl-7 text-sm"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        {typeKeys.length > 1 ? (
          <label className="flex items-center gap-1 text-xs text-muted">
            Type
            <select
              className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink"
              value={type ?? ''}
              onChange={(e) => setParams(e.target.value ? { type: e.target.value } : {})}
            >
              <option value="">Any</option>
              {typeKeys.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="flex items-center gap-1.5 text-xs text-muted">
          <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />{' '}
          Archived
        </label>
      </div>
      {list.isPending ? (
        <Skeleton className="h-40" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.length ? (
        <ul aria-label="Entities" className="flex flex-col">
          {list.data.map((e) => (
            <li key={e.id} className="border-b border-hair-soft last:border-0">
              <Link
                to={`/entities/${e.id}`}
                className="flex flex-wrap items-baseline gap-x-3 py-2 text-sm hover:bg-surface-2"
              >
                <span className="font-medium">{e.name}</span>
                <span className="text-xs text-muted">{humanize(e.type)}</span>
                {e.aliases.length ? (
                  <span className="truncate text-xs text-muted">also {e.aliases.join(', ')}</span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState icon={Building2} title={deferred ? 'Nothing matches' : 'No entities yet'}>
          {deferred ? 'Try another name.' : 'Agents add vendors here as they read documents.'}
        </EmptyState>
      )}
    </div>
  );
}

/** `/entities/:entityId`: the profile, aliases, bank display, records, and what happened. */
export function EntityPage() {
  const { entityId = '' } = useParams();
  const entity = useEntity(entityId);
  const records = useRecords(null, { entity_id: entityId });
  const activity = useEntityActivity(entityId);
  const actions = useEntityActions(entityId);
  const others = useEntities('', entity.data?.type ?? null);
  const isAdmin = useMe().data?.user.role === 'admin';
  const people = usePeople('', 'all').data ?? [];
  const skills = useSkills({ scope_type: 'entity', scope_id: entityId, status: 'active' });
  const [alias, setAlias] = useState('');
  const [mergeInto, setMergeInto] = useState('');
  if (entity.isPending) return <Skeleton className="m-8 h-64" />;
  if (entity.isError) return <ErrorState error={entity.error} onRetry={() => void entity.refetch()} />;
  const e = entity.data;
  const bank = (e.attributes as { bank?: { display?: string } }).bank?.display;
  const profile = Object.entries(e.profile ?? {});
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-6 py-8">
      <header className="flex flex-col gap-1">
        <Link to={`/entities?type=${e.type}`} className="text-xs text-accent hover:underline">
          {humanize(e.type)}s
        </Link>
        <h1 className="page-title">{e.name}</h1>
        {e.status !== 'active' ? <p className="text-sm text-warn">This entity is {e.status}.</p> : null}
      </header>
      <section aria-label="Details" className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1 text-sm">
          <h2 className="section-label">Also known as</h2>
          {e.aliases.length ? <p>{e.aliases.join(', ')}</p> : <p className="text-muted">No other names.</p>}
          <form
            className="flex gap-1.5"
            onSubmit={(ev) => {
              ev.preventDefault();
              if (alias.trim()) actions.alias.mutate(alias.trim(), { onSuccess: () => setAlias('') });
            }}
          >
            <input
              aria-label="Add another name"
              placeholder="Add another name"
              className="h-7 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm"
              value={alias}
              onChange={(ev) => setAlias(ev.target.value)}
            />
            <Button size="sm" type="submit" disabled={!alias.trim()}>
              Add
            </Button>
          </form>
          {bank ? <p className="mt-1 text-xs text-muted">Bank account {bank}</p> : null}
        </div>
        <div className="flex flex-col gap-1 text-sm">
          <h2 className="section-label">Profile</h2>
          {profile.length ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-xs">
              {profile.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{humanize(k)}</dt>
                  <dd>{v == null ? '—' : String(v)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-xs text-muted">Built overnight from its records; none yet.</p>
          )}
        </div>
      </section>
      <section aria-label="Its records" className="flex flex-col gap-1.5">
        <h2 className="section-label">Records</h2>
        {records.data?.length ? (
          <ul className="flex flex-col text-sm">
            {records.data.map((r) => (
              <li
                key={r.id}
                className="flex items-center gap-2 border-b border-hair-soft py-1.5 last:border-0"
              >
                <Link to={`/records/${r.id}`} className="text-accent hover:underline">
                  {r.title}
                </Link>
                <RecordStatus status={r.status} />
                {r.amount != null ? (
                  <span className="ml-auto text-xs tabular-nums text-muted">
                    {r.amount} {r.currency}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No records you can see.</p>
        )}
      </section>
      <section aria-label="Skills for it" className="flex flex-col gap-1.5">
        <h2 className="section-label">What agents know about it</h2>
        {skills.data?.length ? (
          <ul className="flex flex-col gap-1 text-sm">
            {skills.data.map((s) => (
              <li key={s.id}>
                <span className="text-amber-ink">✦ </span>
                {skillText(s)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No skills just for this one.</p>
        )}
      </section>
      <section aria-label="Activity" className="flex flex-col gap-1.5">
        <h2 className="section-label">What happened</h2>
        <ol className="flex flex-col gap-1 text-xs">
          {(activity.data ?? []).map((a) => (
            <li key={a.id}>
              <span className="font-medium">{humanize(a.verb.split('.').pop() ?? a.verb)}</span>{' '}
              <span className="text-muted">
                by{' '}
                {a.actor_kind === 'agent'
                  ? '✦ an agent'
                  : (people.find((p) => p.id === a.actor_id)?.name ?? 'someone')}{' '}
                · {formatRelative(a.created_at)}
              </span>
            </li>
          ))}
        </ol>
      </section>
      {isAdmin && e.status === 'active' ? (
        <section
          aria-label="Manage"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-hairline p-3 text-sm"
        >
          <label className="flex items-center gap-1 text-xs text-muted">
            Merge into
            <select
              className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink"
              value={mergeInto}
              onChange={(ev) => setMergeInto(ev.target.value)}
            >
              <option value="">Choose…</option>
              {(others.data ?? [])
                .filter((o) => o.id !== e.id)
                .map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
            </select>
          </label>
          <Button
            size="sm"
            disabled={!mergeInto || actions.merge.isPending}
            onClick={() =>
              actions.merge.mutate(mergeInto, {
                onSuccess: () => toast.success('Merged: its records, names and skills moved'),
              })
            }
          >
            <Icon icon={Merge} size={14} /> Merge
          </Button>
          <Button
            size="sm"
            variant="text"
            disabled={actions.archive.isPending}
            onClick={() => actions.archive.mutate()}
          >
            <Icon icon={Archive} size={14} /> Archive
          </Button>
        </section>
      ) : null}
    </div>
  );
}
