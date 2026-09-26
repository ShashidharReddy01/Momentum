import { Skeleton } from '@/components/ui/Skeleton';
import { useAdminAiSettings, useAdminAiSettingsMutation, useAdminAiUsage, type AiConfig } from './queries';

function money(v: string | number): string {
  return `$${Number(v).toFixed(2)}`;
}

/** S3.5.2: the admin-only half of `/settings/ai` — enable/disable, budget, auto-apply policy,
 * model aliases (read-only) and usage by feature/user/day. Each toggle is a workspace *override*
 * on top of the deployment's own settings (see `AiConfig`'s docstring): unchecking a box sets an
 * explicit override, re-checking it clears back to "follow the deployment" rather than forcing a
 * `true` the deployment might not allow. */
export function AdminAiSection() {
  const settings = useAdminAiSettings();
  const save = useAdminAiSettingsMutation();
  const usage = useAdminAiUsage(30);

  if (settings.isPending) {
    return (
      <div className="mt-4 flex flex-col gap-2">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    );
  }
  if (!settings.data) return null;
  const { config, effective, models } = settings.data;
  const patch = (next: Partial<AiConfig>) => save.mutate({ ...config, ...next });

  return (
    <>
      <section aria-labelledby="admin-ai-title" className="mt-8">
        <h2 id="admin-ai-title" className="text-[15px] font-semibold">
          Admin
        </h2>
        <label className="mt-3 flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={effective.enabled}
            disabled={save.isPending}
            onChange={(e) => patch({ enabled: e.target.checked ? null : false })}
          />
          <span>
            Mo is turned on for this workspace
            <span className="block text-muted">
              Turning this off stops every AI feature for everyone here, regardless of individual preferences.
              It can't turn Mo on if the deployment itself has disabled AI.
            </span>
          </span>
        </label>
        <label className="mt-4 flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={effective.allow_auto_apply}
            disabled={save.isPending}
            onChange={(e) => patch({ allow_auto_apply: e.target.checked ? null : false })}
          />
          <span>
            Members may let Mo apply low-risk changes without asking
            <span className="block text-muted">
              Turns off everyone's "apply low-risk changes from Mo without asking" preference at once.
              Previews and manual apply still work.
            </span>
          </span>
        </label>
        <div className="mt-4 text-sm">
          <label htmlFor="ai-monthly-budget" className="block">
            Monthly budget (USD)
          </label>
          <div className="mt-1 flex items-center gap-2">
            <input
              id="ai-monthly-budget"
              type="number"
              min={0}
              step="0.01"
              className="w-32 rounded-md border border-hair-soft bg-transparent px-2 py-1 text-sm"
              placeholder={String(effective.monthly_budget_usd)}
              value={config.monthly_budget_usd ?? ''}
              disabled={save.isPending}
              onChange={(e) => {
                const v = e.target.value;
                patch({ monthly_budget_usd: v === '' ? null : Number(v) });
              }}
            />
            <span className="text-muted">0 = unlimited; blank uses the deployment default</span>
          </div>
        </div>
        <div className="mt-4 text-sm">
          <span className="text-muted">Model aliases (set by the deployment)</span>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            {(['fast', 'default', 'smart', 'embed'] as const).map((alias) => (
              <div className="contents" key={alias}>
                <dt className="text-muted">{alias}</dt>
                <dd className="truncate font-mono">{models[alias]}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>
      <section aria-labelledby="usage-title" className="mt-8">
        <h2 id="usage-title" className="text-[15px] font-semibold">
          Usage (last 30 days)
        </h2>
        {usage.isPending ? (
          <Skeleton className="mt-3 h-20 w-full" />
        ) : usage.data ? (
          <>
            <p className="mt-1 text-sm text-muted">
              {money(usage.data.month_spend_usd)} spent this month
              {effective.monthly_budget_usd > 0 ? ` of a ${money(effective.monthly_budget_usd)} budget` : ''}.
            </p>
            <UsageTable
              caption="By feature"
              rows={usage.data.by_feature.map((r) => ({ label: r.feature, ...r }))}
            />
            <UsageTable
              caption="By person"
              rows={usage.data.by_user.map((r) => ({ label: r.user_name ?? 'Agent', ...r }))}
            />
            <UsageTable caption="By day" rows={usage.data.by_day.map((r) => ({ label: r.day, ...r }))} />
          </>
        ) : null}
      </section>
    </>
  );
}

function UsageTable({
  caption,
  rows,
}: {
  caption: string;
  rows: {
    label: string;
    calls: number;
    tokens_in: number;
    tokens_out: number;
    cost_usd: string;
    errors: number;
  }[];
}) {
  if (!rows.length) return null;
  return (
    <table className="mt-3 w-full text-sm">
      <caption className="mb-1 text-left text-xs text-muted-2">{caption}</caption>
      <thead>
        <tr className="text-left text-xs text-muted-2">
          <th className="pb-2 font-medium"> </th>
          <th className="pb-2 font-medium">Calls</th>
          <th className="pb-2 font-medium">Tokens in</th>
          <th className="pb-2 font-medium">Tokens out</th>
          <th className="pb-2 font-medium">Cost</th>
          <th className="pb-2 font-medium">Errors</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} className="border-t border-hair-soft">
            <td className="py-2 pr-3">{r.label}</td>
            <td className="py-2 pr-3">{r.calls}</td>
            <td className="py-2 pr-3">{r.tokens_in}</td>
            <td className="py-2 pr-3">{r.tokens_out}</td>
            <td className="py-2 pr-3">{money(r.cost_usd)}</td>
            <td className="py-2">{r.errors}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
