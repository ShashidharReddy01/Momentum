import { CheckCircle2, Download, Loader2, PauseCircle, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';
import { toastError } from '@/lib/toast';
import { useAsanaDiscover, useImportRunner, useImports, type AsanaThing, type ImportJob } from './queries';

/** What each count in a report means, in the order a person reads it. */
const REPORT: [string, string][] = [
  ['projects', 'Projects'],
  ['sections', 'Sections'],
  ['tasks', 'Tasks'],
  ['subtasks', 'Subtasks'],
  ['milestones', 'Milestones'],
  ['approvals', 'Approvals'],
  ['placements', 'Tasks also in another project'],
  ['custom_fields', 'Custom fields'],
  ['field_values', 'Field values'],
  ['tags', 'Tags'],
  ['followers', 'Followers'],
  ['dependencies', 'Dependencies'],
  ['comments', 'Comments'],
  ['attachments', 'Files'],
  ['attachment_links', 'Files kept as links'],
  ['status_updates', 'Status updates'],
  ['likes', 'Likes'],
  ['users_matched', 'People matched to accounts'],
  ['users_invited', 'People invited'],
  ['users_unmatched', 'People not matched'],
];

/**
 * S7.4.2: import from Asana, one step at a time: a personal access token (kept in this page's
 * memory only, sent with each call, never stored) → a workspace → a team → which projects →
 * a dry run (counts and anything that can't be mapped) → the import, with progress. A large
 * import can pause and resume; the CLI (`momentum asana-import`) runs the same import from a
 * terminal.
 */
export function AsanaImportPage() {
  const [pat, setPat] = useState('');
  const [workspaces, setWorkspaces] = useState<AsanaThing[] | null>(null);
  const [workspace, setWorkspace] = useState('');
  const [teams, setTeams] = useState<AsanaThing[] | null>(null);
  const [team, setTeam] = useState('');
  const [projects, setProjects] = useState<AsanaThing[] | null>(null);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [teamName, setTeamName] = useState('');
  const [invite, setInvite] = useState(true);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [running, setRunning] = useState(false);
  const discover = useAsanaDiscover();
  const runner = useImportRunner();
  const recent = useImports().data ?? [];

  const connect = (e: FormEvent) => {
    e.preventDefault();
    setWorkspaces(null);
    setTeams(null);
    setProjects(null);
    discover.mutate(
      { pat },
      {
        onSuccess: (d) => {
          setWorkspaces(d.workspaces);
          if (d.workspaces.length === 1) pickWorkspace(d.workspaces[0]!.gid);
        },
      },
    );
  };
  const pickWorkspace = (gid: string) => {
    setWorkspace(gid);
    setTeam('');
    setProjects(null);
    discover.mutate({ pat, workspace_gid: gid }, { onSuccess: (d) => setTeams(d.teams) });
  };
  const pickTeam = (gid: string) => {
    setTeam(gid);
    setTeamName(teams?.find((t) => t.gid === gid)?.name ?? '');
    discover.mutate(
      { pat, workspace_gid: workspace, team_gid: gid },
      {
        onSuccess: (d) => {
          setProjects(d.projects);
          setPicked(new Set(d.projects.map((p) => p.gid)));
        },
      },
    );
  };

  const start = async (dryRun: boolean) => {
    if (!projects || !picked.size) return;
    setRunning(true);
    try {
      const all = picked.size === projects.length;
      const created = await runner.create({
        workspace_gid: workspace,
        team_gid: team,
        team_name: teamName.trim() || 'Imported team',
        project_gids: all ? null : [...picked],
        dry_run: dryRun,
        invite_unmatched: invite,
      });
      await runner.run(created, pat, setJob);
    } catch (e) {
      toastError(e, 'The import stopped');
    } finally {
      setRunning(false);
    }
  };
  const resume = async (j: ImportJob) => {
    if (!pat) return;
    setRunning(true);
    try {
      await runner.run(j, pat, setJob);
    } catch (e) {
      toastError(e, 'The import stopped');
    } finally {
      setRunning(false);
    }
  };
  // leaving the page stops the loop after the step in flight (the job keeps its place)
  useEffect(() => () => runner.stop(), [runner]);

  return (
    <div className="min-w-0 flex-1 overflow-auto px-4 py-6 md:px-8">
      <h1 className="page-title mb-1 flex items-center gap-2">
        <Icon icon={Download} size={20} /> Import from Asana
      </h1>
      <p className="mb-6 max-w-2xl text-sm text-muted">
        Brings over projects, sections, tasks and subtasks, custom fields, comments, files, followers,
        dependencies and status updates, keeping who did what and when. Run a dry run first to see what will
        come over. Importing again later adds only what's new.
      </p>

      <div className="flex max-w-2xl flex-col gap-6">
        <Step n={1} title="Connect to Asana" done={!!workspaces}>
          <form onSubmit={connect} className="flex flex-col gap-2">
            <label className="flex flex-col gap-1 text-sm">
              Personal Access Token
              <input
                type="password"
                required
                autoComplete="off"
                value={pat}
                onChange={(e) => setPat(e.target.value)}
                className="h-9 rounded-md border border-hairline bg-surface px-2 text-sm"
              />
            </label>
            <p className="text-xs text-muted">
              In Asana: your profile photo → Settings → Apps → Developer apps → Create new token. It's used
              while this page is open and never stored.
            </p>
            <Button type="submit" size="sm" className="w-fit" disabled={!pat || discover.isPending}>
              {discover.isPending && !workspaces ? 'Connecting…' : 'Connect'}
            </Button>
          </form>
        </Step>

        {workspaces ? (
          <Step n={2} title="Choose the workspace and team" done={!!projects}>
            <div className="flex flex-col gap-3">
              <Picker
                label="Asana workspace"
                value={workspace}
                options={workspaces}
                onChange={pickWorkspace}
              />
              {teams ? <Picker label="Asana team" value={team} options={teams} onChange={pickTeam} /> : null}
              {teams && !teams.length ? (
                <p className="text-sm text-muted">This workspace has no teams the token can see.</p>
              ) : null}
            </div>
          </Step>
        ) : null}

        {projects ? (
          <Step n={3} title="Choose what to import" done={!!job?.dry_run && job.status === 'done'}>
            <fieldset className="flex flex-col gap-1">
              <legend className="mb-1 text-sm">
                Projects ({picked.size} of {projects.length})
              </legend>
              <div className="max-h-64 overflow-auto rounded-md border border-hair-soft p-1">
                {projects.map((p) => (
                  <label
                    key={p.gid}
                    className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-surface-2"
                  >
                    <input
                      type="checkbox"
                      checked={picked.has(p.gid)}
                      onChange={() =>
                        setPicked((s) => {
                          const n = new Set(s);
                          if (n.has(p.gid)) n.delete(p.gid);
                          else n.add(p.gid);
                          return n;
                        })
                      }
                      className="accent-[var(--accent)]"
                    />
                    <span className="truncate">{p.name}</span>
                    {p.archived ? <span className="text-xs text-muted">archived</span> : null}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="mt-3 flex flex-col gap-1 text-sm">
              Team name in Momentum
              <input
                value={teamName}
                onChange={(e) => setTeamName(e.target.value)}
                maxLength={120}
                className="h-9 rounded-md border border-hairline bg-surface px-2 text-sm"
              />
            </label>
            <label className="mt-2 flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={invite}
                onChange={(e) => setInvite(e.target.checked)}
                className="mt-0.5 accent-[var(--accent)]"
              />
              <span>
                Invite people from Asana who don't have an account yet
                <span className="block text-xs text-muted">
                  Their tasks keep their assignee; they join when they first sign in with the same email.
                </span>
              </span>
            </label>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="ghost" disabled={running || !picked.size} onClick={() => void start(true)}>
                Dry run
              </Button>
              <Button disabled={running || !picked.size} onClick={() => void start(false)}>
                Import
              </Button>
            </div>
          </Step>
        ) : null}

        {job ? <Progress job={job} running={running} onStop={runner.stop} /> : null}

        {recent.length ? (
          <section aria-labelledby="recent-imports">
            <h2 id="recent-imports" className="section-label mb-2">
              Recent imports
            </h2>
            <ul className="flex flex-col divide-y divide-hair-soft rounded-md border border-hair-soft">
              {recent.map((j) => (
                <li key={j.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">
                    {j.dry_run ? 'Dry run' : 'Import'} · {new Date(j.created_at).toLocaleString()}
                  </span>
                  <span className="text-xs text-muted">{statusWords(j)}</span>
                  {j.status !== 'done' && j.status !== 'failed' ? (
                    <Button
                      size="sm"
                      variant="text"
                      disabled={running || !pat}
                      title={pat ? undefined : 'Enter the token above to resume'}
                      onClick={() => void resume(j)}
                    >
                      Resume
                    </Button>
                  ) : (
                    <Button size="sm" variant="text" onClick={() => setJob(j)}>
                      Report
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </div>
  );
}

function statusWords(j: ImportJob): string {
  if (j.status === 'done') return 'Finished';
  if (j.status === 'failed') return 'Failed';
  return `Paused · ${j.remaining} steps left`;
}

function Step({
  n,
  title,
  done,
  children,
}: {
  n: number;
  title: string;
  done: boolean;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`import-step-${n}`}
      className="rounded-lg border border-hair-soft bg-surface p-4"
    >
      <h2 id={`import-step-${n}`} className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <span
          className={cn(
            'tabular flex size-5 items-center justify-center rounded-full text-[11px]',
            done ? 'bg-ok text-on-accent' : 'bg-surface-2 text-ink-2',
          )}
          aria-hidden
        >
          {done ? '✓' : n}
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Picker({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: AsanaThing[];
  onChange: (gid: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <select
        value={value}
        onChange={(e) => e.target.value && onChange(e.target.value)}
        className="h-9 rounded-md border border-hairline bg-surface px-2 text-sm"
      >
        <option value="">Choose…</option>
        {options.map((o) => (
          <option key={o.gid} value={o.gid}>
            {o.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function Progress({ job, running, onStop }: { job: ImportJob; running: boolean; onStop: () => void }) {
  const stats = useMemo(() => (job.stats ?? {}) as Record<string, unknown>, [job.stats]);
  const rows = useMemo(() => REPORT.filter(([k]) => typeof stats[k] === 'number' && stats[k]), [stats]);
  const skipped = Array.isArray(stats.skipped_items) ? (stats.skipped_items as string[]) : [];
  const skippedCount = typeof stats.skipped === 'number' ? stats.skipped : skipped.length;
  const unmapped = (stats.unmapped ?? {}) as Record<string, number>;
  const done = job.status === 'done';
  const title = done
    ? job.dry_run
      ? 'Dry run finished: nothing was changed'
      : 'Import finished'
    : running
      ? job.dry_run
        ? 'Dry run in progress…'
        : 'Importing…'
      : 'Paused';
  return (
    <section
      aria-labelledby="import-progress"
      aria-live="polite"
      className="rounded-lg border border-hair-soft bg-surface-2 p-4"
    >
      <h2 id="import-progress" className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Icon
          icon={done ? CheckCircle2 : running ? Loader2 : PauseCircle}
          size={16}
          className={cn(
            done ? 'text-ok' : 'text-muted',
            running && !done && 'animate-spin motion-reduce:animate-none',
          )}
        />
        {title}
        {!done ? <span className="text-xs font-normal text-muted">{job.remaining} steps left</span> : null}
        {running && !done ? (
          <Button size="sm" variant="text" className="ml-auto" onClick={onStop}>
            Pause
          </Button>
        ) : null}
      </h2>
      {job.dry_run && done ? (
        <p className="mb-3 text-xs text-muted">
          Comments, files and status updates are counted by the import itself (each is its own request to
          Asana).
        </p>
      ) : null}
      <dl
        aria-label={job.dry_run ? 'Would import' : 'Imported'}
        className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3"
      >
        {rows.map(([k, label]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-muted">{label}</dt>
            <dd className="tabular font-medium">{String(stats[k])}</dd>
          </div>
        ))}
      </dl>
      {Object.keys(unmapped).length ? (
        <ul aria-label="Imported differently" className="mt-3 text-xs text-ink-2">
          {Object.entries(unmapped).map(([what, n]) => (
            <li key={what}>
              {n} × {what}
            </li>
          ))}
        </ul>
      ) : null}
      {skippedCount ? (
        <details className="mt-3 text-sm">
          <summary className="flex cursor-pointer items-center gap-1 text-warn">
            <Icon icon={TriangleAlert} size={14} /> {skippedCount} not imported
          </summary>
          <ul
            aria-label="Not imported"
            className="mt-1 max-h-48 list-disc overflow-auto pl-5 text-xs text-ink-2"
          >
            {skipped.map((s) => (
              <li key={s}>{s}</li>
            ))}
            {skippedCount > skipped.length ? <li>…and {skippedCount - skipped.length} more</li> : null}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
