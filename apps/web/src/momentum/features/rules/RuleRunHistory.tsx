import { Command } from 'cmdk';
import { AlertTriangle, CheckCircle2, MinusCircle, PlayCircle } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { cn } from '@/lib/cn';
import { useSearchProjectTasks, type TaskSummary } from '@/features/tasks';
import { useRuleRuns, useTestRun, type RuleOut, type RuleTestRun } from './queries';

const STATUS: Record<string, { icon: typeof CheckCircle2; className: string; label: string }> = {
  success: { icon: CheckCircle2, className: 'text-ok', label: 'Success' },
  failed: { icon: AlertTriangle, className: 'text-crit', label: 'Failed' },
  skipped: { icon: MinusCircle, className: 'text-muted', label: 'Skipped' },
};

function RunRow({
  run,
}: {
  run: { status: string; error: string | null; actions_run: number; started_at: string };
}) {
  const s = STATUS[run.status] ?? STATUS.skipped!;
  return (
    <li className="flex items-start gap-2 border-b border-hair-soft py-2 text-sm last:border-0">
      <Icon icon={s.icon} size={15} className={cn('mt-0.5 shrink-0', s.className)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={s.className}>{s.label}</span>
          <span className="text-xs text-muted-2">{new Date(run.started_at).toLocaleString()}</span>
        </div>
        {run.error ? <p className="text-xs text-muted">{run.error}</p> : null}
        {run.status === 'success' ? (
          <p className="text-xs text-muted">
            {run.actions_run} action{run.actions_run === 1 ? '' : 's'} run
          </p>
        ) : null}
      </div>
    </li>
  );
}

function TestRunTaskPicker({
  projectId,
  onSelect,
}: {
  projectId: string;
  onSelect: (t: TaskSummary) => void;
}) {
  const [q, setQ] = useState('');
  const results = useSearchProjectTasks(projectId, q);
  return (
    <Command label="Tasks" loop shouldFilter={false}>
      <Command.Input
        value={q}
        onValueChange={setQ}
        placeholder="Search tasks to test on…"
        className="h-10 w-full border-b border-hair-soft bg-transparent px-3 text-sm outline-none placeholder:text-muted-2"
      />
      <Command.List className="max-h-64 overflow-auto p-1">
        <Command.Empty className="px-3 py-4 text-center text-sm text-muted">
          {results.isPending ? 'Loading…' : 'No tasks found'}
        </Command.Empty>
        {(results.data ?? []).map((t) => (
          <Command.Item
            key={t.id}
            value={t.id}
            onSelect={() => onSelect(t)}
            className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm data-[selected=true]:bg-surface-2"
          >
            <span className="truncate">{t.title}</span>
          </Command.Item>
        ))}
      </Command.List>
    </Command>
  );
}

function TestRunResultView({ result, taskTitle }: { result: RuleTestRun; taskTitle: string }) {
  if (!result.conditions_passed) {
    return (
      <p className="rounded-md bg-surface-2 px-3 py-2 text-sm text-muted">
        The conditions don't match "{taskTitle}" — no actions would run.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-1 rounded-md bg-surface-2 px-3 py-2 text-sm">
      {result.actions.map((a, i) => (
        <li key={i} className="flex items-center gap-2">
          <Icon
            icon={a.ok ? CheckCircle2 : AlertTriangle}
            size={14}
            className={a.ok ? 'text-ok' : 'text-crit'}
          />
          <span>{a.type}</span>
          {a.error ? <span className="text-xs text-muted">— {a.error}</span> : null}
        </li>
      ))}
    </ul>
  );
}

/** Run history (S4.1.1's executor writes one `RuleRun` per event it handles) plus a "test run"
 * that previews the rule's actions against a chosen task without persisting anything. */
export function RuleRunHistory({ rule }: { rule: RuleOut }) {
  const runs = useRuleRuns(rule.id, true);
  const testRun = useTestRun(rule.id);
  const [picking, setPicking] = useState(false);
  const [tested, setTested] = useState<{ title: string; result: RuleTestRun } | null>(null);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="section-label">Test run</span>
        <Popover open={picking} onOpenChange={setPicking}>
          <PopoverTrigger asChild>
            <Button size="sm" variant="ghost">
              <Icon icon={PlayCircle} /> Test on a task…
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-72 p-0">
            <TestRunTaskPicker
              projectId={rule.project_id ?? ''}
              onSelect={(t) => {
                setPicking(false);
                testRun.mutate(t.id, {
                  onSuccess: (result) => setTested({ title: t.title, result }),
                });
              }}
            />
          </PopoverContent>
        </Popover>
      </div>
      {tested ? <TestRunResultView result={tested.result} taskTitle={tested.title} /> : null}

      <span className="section-label">Run history</span>
      {runs.isPending ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : runs.data?.length ? (
        <ul aria-label="Run history">
          {runs.data.map((r) => (
            <RunRow key={r.id} run={r} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">This rule hasn't run yet.</p>
      )}
    </div>
  );
}
