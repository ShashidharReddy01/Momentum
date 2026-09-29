import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { useAgentStats, useUpdateAgent, type Agent } from './queries';
import { AUTONOMY_LABEL, money } from './runMeta';

/** S5.1.4: the admin's controls for one agent: on/off, autonomy (acting alone must be earned:
 * the stats say why it can or can't be promoted), and its monthly budget next to what it has
 * spent. Everything here is a PATCH; the server enforces the same rules. */
export function AgentSettings({ agent }: { agent: Agent }) {
  const stats = useAgentStats(agent.id, true);
  const save = useUpdateAgent(agent.id);
  const [usd, setUsd] = useState(String(agent.budget_monthly_usd));
  const [tokens, setTokens] = useState(String(agent.budget_monthly_tokens));
  const s = stats.data;
  const canPromote = agent.autonomy === 'auto' || !!s?.eligible_for_auto;
  const rate = s?.acceptance_rate;

  return (
    <section
      aria-label="Agent settings"
      className="flex flex-col gap-4 rounded-lg border border-hairline p-4"
    >
      <h2 className="text-sm font-semibold">Settings</h2>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={agent.enabled}
          disabled={save.isPending}
          onChange={(e) => save.mutate({ enabled: e.target.checked, expected_version: agent.version })}
        />
        <span>
          {agent.name} is on
          <span className="block text-muted">
            When off, nothing triggers it and queued runs are cancelled.
          </span>
        </span>
      </label>

      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor="agent-autonomy">Autonomy</label>
        <select
          id="agent-autonomy"
          className="w-fit rounded-md border border-hairline bg-surface px-2 py-1"
          value={agent.autonomy}
          disabled={save.isPending}
          onChange={(e) =>
            save.mutate({
              autonomy: e.target.value as Agent['autonomy'],
              expected_version: agent.version,
            })
          }
        >
          <option value="suggest">{AUTONOMY_LABEL.suggest}</option>
          <option value="confirm">{AUTONOMY_LABEL.confirm}</option>
          <option value="auto" disabled={!canPromote}>
            {AUTONOMY_LABEL.auto}
            {canPromote ? '' : ' (not earned yet)'}
          </option>
        </select>
        {stats.isPending ? (
          <Skeleton className="h-4 w-72" />
        ) : s ? (
          <p className="text-xs text-muted">
            {s.decided
              ? `Accepted ${s.accepted} of its last ${s.decided} proposals (${Math.round((rate ?? 0) * 100)}%)`
              : 'No decided proposals yet'}
            {' · '}
            {s.undos_14d ? `${s.undos_14d} undone in the last 14 days` : 'nothing undone in the last 14 days'}
            {agent.autonomy !== 'auto' ? (
              s.eligible_for_auto ? (
                <span className="block text-ok">It can be promoted to act on its own.</span>
              ) : (
                <span className="block">Acting on its own needs: {s.reasons.join('; ')}.</span>
              )
            ) : (
              <span className="block">
                It goes back to asking first if more than 10% of its own changes are undone in a week (
                {s.auto_undone_7d} of {s.auto_applied_7d} this week).
              </span>
            )}
          </p>
        ) : null}
      </div>

      <form
        className="flex flex-wrap items-end gap-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({
            budget_monthly_usd: usd,
            budget_monthly_tokens: Number(tokens),
            expected_version: agent.version,
          });
        }}
      >
        <label className="flex flex-col gap-1">
          Monthly budget (USD)
          <input
            className="w-28 rounded-md border border-hairline bg-surface px-2 py-1"
            inputMode="decimal"
            value={usd}
            onChange={(e) => setUsd(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          Token cap while unpriced
          <input
            className="w-32 rounded-md border border-hairline bg-surface px-2 py-1"
            inputMode="numeric"
            value={tokens}
            onChange={(e) => setTokens(e.target.value)}
          />
        </label>
        <Button type="submit" variant="ghost" size="sm" loading={save.isPending}>
          Save budget
        </Button>
        {s ? (
          <p className="w-full text-xs text-muted">
            This month: {s.priced ? money(s.month_usd) : 'cost not measured (model unpriced)'} ·{' '}
            {s.month_tokens.toLocaleString()} tokens.{' '}
            {s.priced ? 'The dollar budget applies.' : 'The token cap applies until the model has a price.'}
          </p>
        ) : null}
      </form>
    </section>
  );
}
