import { Link } from 'react-router';
import { AICallout } from '@/components/common/AI';
import { formatRelative } from '@/lib/dates';
import { useProjectRisk } from './queries';

const LEVEL: Record<string, string> = {
  high: 'High risk',
  medium: 'Some risk',
  low: 'Low risk',
  none: 'No risk signals',
};

/** S5.3.7: Radar's latest note on this project, from its weekday check. Nothing when Radar isn't
 * watching the project; a quiet line when it found nothing. */
export function RiskNote({ projectId }: { projectId: string }) {
  const risk = useProjectRisk(projectId).data;
  if (!risk) return null;
  const when = formatRelative(risk.at);
  if (risk.level === 'none') {
    return (
      <p className="text-xs text-muted">
        ✦ {risk.agent_name} found no risk signals ({when}).
      </p>
    );
  }
  return (
    <AICallout
      label={`${risk.agent_name} · ${LEVEL[risk.level] ?? risk.level}`}
      actions={
        <Link to={`/agents/runs/${risk.run_id}`} className="text-xs text-amber-ink hover:underline">
          How Radar decided · {when}
        </Link>
      }
    >
      {risk.summary ? <p className="mb-1.5 text-ink">{risk.summary}</p> : null}
      <ul aria-label="Risk signals" className="list-disc space-y-0.5 pl-5 text-xs">
        {risk.signals.map((s) => (
          <li key={s.kind}>
            {s.text}
            {s.tasks.length ? <span className="text-muted">: {s.tasks.join(', ')}</span> : null}
          </li>
        ))}
      </ul>
    </AICallout>
  );
}
