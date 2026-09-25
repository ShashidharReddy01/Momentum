import { FolderKanban, ListChecks, MessageSquare, Search as SearchIcon, User } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router';
import { EmptyState } from '@/components/common/States';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import { TaskNavProvider, TaskPane, useTaskNav } from '@/features/tasks';
import { useSearch, type SearchFilters } from './queries';

const TYPE_LABEL: Record<string, string> = {
  task: 'Tasks',
  project: 'Projects',
  person: 'People',
  comment: 'Comments',
};
const TYPES = ['task', 'project', 'person', 'comment'];

/** S2.6.2: the full results page (⌘K's "quick results" links here for anything past the top
 * few). Filters (type, project, assignee, completed) live in the URL so a search is shareable
 * and survives a refresh. */
export function SearchPage() {
  return (
    <TaskNavProvider>
      <SearchPageBody />
    </TaskNavProvider>
  );
}

function SearchPageBody() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get('q') ?? '');
  const nav = useTaskNav()!;
  const projects = useProjects().data ?? [];
  const people = usePeople().data ?? [];

  const activeTypes = params.get('type')?.split(',').filter(Boolean) ?? TYPES;
  const projectId = params.get('project_id') ?? '';
  const assigneeId = params.get('assignee_id') ?? '';
  const completedParam = params.get('completed');

  const filters: SearchFilters = {
    type: activeTypes.length < TYPES.length ? activeTypes.join(',') : undefined,
    project_id: projectId || undefined,
    assignee_id: assigneeId || undefined,
    completed: completedParam === null ? undefined : completedParam === 'true',
    limit: 30,
  };
  const results = useSearch(q, filters);

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const toggleType = (t: string) => {
    const set = new Set(activeTypes);
    if (set.has(t)) set.delete(t);
    else set.add(t);
    setParam('type', set.size === TYPES.length || set.size === 0 ? null : [...set].join(','));
  };

  const submitQuery = (e: FormEvent) => {
    e.preventDefault();
    setParam('q', q || null);
  };

  const data = results.data;
  const noResults =
    !!data && !data.tasks.length && !data.projects.length && !data.people.length && !data.comments.length;

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto px-4 md:px-8 py-6">
        <h1 className="page-title mb-4 flex items-center gap-2">
          <Icon icon={SearchIcon} size={20} /> Search
        </h1>

        <form onSubmit={submitQuery} className="mb-3">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search tasks, projects, people, comments…"
            className="h-10 w-full max-w-lg rounded-md border border-hair bg-surface px-3 text-sm"
          />
        </form>

        <div className="mb-6 flex flex-wrap items-center gap-3 text-sm">
          <div className="flex gap-1">
            {TYPES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => toggleType(t)}
                className={`h-7 rounded-full border px-3 text-xs ${
                  activeTypes.includes(t)
                    ? 'border-accent bg-accent-tint text-ink'
                    : 'border-hair text-muted hover:text-ink'
                }`}
              >
                {TYPE_LABEL[t]}
              </button>
            ))}
          </div>
          <select
            value={projectId}
            onChange={(e) => setParam('project_id', e.target.value || null)}
            className="h-7 rounded-md border border-hair bg-surface px-2 text-xs"
          >
            <option value="">Any project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={assigneeId}
            onChange={(e) => setParam('assignee_id', e.target.value || null)}
            className="h-7 rounded-md border border-hair bg-surface px-2 text-xs"
          >
            <option value="">Any assignee</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={completedParam ?? ''}
            onChange={(e) => setParam('completed', e.target.value || null)}
            className="h-7 rounded-md border border-hair bg-surface px-2 text-xs"
          >
            <option value="">Completed: any</option>
            <option value="false">Not completed</option>
            <option value="true">Completed</option>
          </select>
        </div>

        {q.trim().length < 2 ? (
          <p className="text-sm text-muted">Type at least 2 characters to search.</p>
        ) : results.isPending ? (
          <div className="flex flex-col gap-2" aria-busy>
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : noResults ? (
          <EmptyState icon={SearchIcon} title="No results">
            Try a different search term or clear a filter.
          </EmptyState>
        ) : (
          <div className="flex flex-col gap-6">
            {data && data.tasks.length ? (
              <section>
                <h2 className="section-label mb-1.5">Tasks</h2>
                <ul className="flex flex-col gap-0.5">
                  {data.tasks.map((t) => (
                    <li key={t.id}>
                      <button
                        type="button"
                        onClick={() => nav.open(t.id)}
                        className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-surface-2"
                      >
                        <Icon icon={ListChecks} size={14} className="shrink-0 text-muted" />
                        <span className="min-w-0 flex-1 truncate">{t.title}</span>
                        {t.project_name ? (
                          <span className="shrink-0 text-xs text-muted-2">{t.project_name}</span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {data && data.projects.length ? (
              <section>
                <h2 className="section-label mb-1.5">Projects</h2>
                <ul className="flex flex-col gap-0.5">
                  {data.projects.map((p) => (
                    <li key={p.id}>
                      <Link
                        to={`/projects/${p.id}`}
                        className="flex h-9 items-center gap-2 rounded-md px-2 text-sm hover:bg-surface-2"
                      >
                        <Icon icon={FolderKanban} size={14} className="shrink-0 text-muted" />
                        <span className="truncate">{p.name}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {data && data.people.length ? (
              <section>
                <h2 className="section-label mb-1.5">People</h2>
                <ul className="flex flex-col gap-0.5">
                  {data.people.map((p) => (
                    <li key={p.id} className="flex h-9 items-center gap-2 px-2 text-sm">
                      <Icon icon={User} size={14} className="shrink-0 text-muted" />
                      <span className="truncate">{p.name}</span>
                      <span className="truncate text-xs text-muted-2">{p.email}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {data && data.comments.length ? (
              <section>
                <h2 className="section-label mb-1.5">Comments</h2>
                <ul className="flex flex-col gap-0.5">
                  {data.comments.map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => nav.open(c.task_id)}
                        className="flex h-auto w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                      >
                        <span className="flex items-center gap-2 text-muted-2">
                          <Icon icon={MessageSquare} size={13} /> {c.task_title}
                        </span>
                        <span className="truncate">{c.snippet}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        )}
      </div>
      {nav.openId ? (
        <TaskPane
          taskId={nav.openId}
          onClose={nav.close}
          onStep={nav.step}
          onOpenTask={(id) => nav.open(id)}
        />
      ) : null}
    </div>
  );
}
