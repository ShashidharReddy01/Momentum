import { Link } from 'react-router';
import { AskBox } from './AskCard';
import { useMyAsks, type Ask } from './platform';

/** Home's "Waiting on you" card (spec §5.2, §12.8): agents' open questions for me, oldest first,
 * answerable right here. Hidden when nothing waits. */
export function WaitingOnYou({ className }: { className?: string }) {
  const asks = useMyAsks();
  const rows = asks.data ?? [];
  if (!rows.length) return null;
  return (
    <section
      aria-label="Waiting on you"
      className={`rounded-lg border border-amber/60 bg-surface p-4 ${className ?? ''}`}
    >
      <div className="mb-2 flex min-h-7 items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold text-ink">Waiting on you</h2>
        <span className="text-xs text-muted">
          {rows.length} question{rows.length === 1 ? '' : 's'}
        </span>
      </div>
      <ul className="flex flex-col gap-2">
        {rows.slice(0, 5).map((a) => (
          <WaitingRow key={a.id} ask={a} />
        ))}
      </ul>
      {rows.length > 5 ? (
        <Link to="/inbox" className="mt-2 inline-block text-xs text-accent hover:underline">
          {rows.length - 5} more in your inbox
        </Link>
      ) : null}
    </section>
  );
}

function WaitingRow({ ask }: { ask: Ask }) {
  return (
    <li>
      <AskBox ask={ask} via="card" compact />
      <Link to={`/task/${ask.task_id}`} className="ml-1 text-xs text-accent hover:underline">
        Open the task
      </Link>
    </li>
  );
}

/** The answer controls on an inbox row for an agent's question (spec §12.8): the open questions
 * for me on that task, answerable without opening it. */
export function InboxAskControls({ taskId }: { taskId: string }) {
  const asks = useMyAsks();
  const rows = (asks.data ?? []).filter((a) => a.task_id === taskId);
  if (!rows.length) return null;
  return (
    <div className="ml-8 flex flex-col gap-1">
      {rows.map((a) => (
        <AskBox key={a.id} ask={a} via="inbox" compact />
      ))}
    </div>
  );
}
