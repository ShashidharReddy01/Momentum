import { AlertTriangle, LayoutDashboard } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePortfolios } from '@/features/portfolios';
import { cn } from '@/lib/cn';
import { ANY_KIND_LABELS } from './model';
import {
  useCreateFromTemplate,
  useDashboardTemplates,
  useTemplatePreview,
  type DashboardDetail,
} from './queries';

/**
 * Phase 7.5 (spec §7.5): "New dashboard → From a template". Pick a role, bind it to a portfolio,
 * and see what it will hold before creating it: fields and stages are matched by name, and
 * whatever doesn't match is listed (its widgets are left out), never dropped silently.
 */
export function TemplateGallery({
  open,
  onOpenChange,
  portfolioId = null,
  portfolioTab = false,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** a portfolio's own tab: bound to it, no choice */
  portfolioId?: string | null;
  portfolioTab?: boolean;
  onCreated: (d: DashboardDetail) => void;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New dashboard from a template"
      className="top-[6vh] w-[min(920px,calc(100vw-32px))]"
    >
      {open ? (
        <Gallery
          fixedPortfolio={portfolioId}
          portfolioTab={portfolioTab}
          onCancel={() => onOpenChange(false)}
          onCreated={onCreated}
        />
      ) : null}
    </Dialog>
  );
}

function Gallery({
  fixedPortfolio,
  portfolioTab,
  onCancel,
  onCreated,
}: {
  fixedPortfolio: string | null;
  portfolioTab: boolean;
  onCancel: () => void;
  onCreated: (d: DashboardDetail) => void;
}) {
  const templates = useDashboardTemplates();
  const portfolios = usePortfolios();
  const [template, setTemplate] = useState<string | null>(null);
  const [portfolio, setPortfolio] = useState<string>(fixedPortfolio ?? '');
  const preview = useTemplatePreview(template, portfolio || null);
  const create = useCreateFromTemplate();

  return (
    <div className="grid max-h-[80vh] grid-cols-1 overflow-auto md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <div className="space-y-3 border-hair-soft px-5 py-4 md:border-r">
        <p className="text-sm text-ink-2">
          Each role dashboard reads a portfolio’s projects and lifecycle, with “me” meaning whoever is
          looking.
        </p>
        {templates.isPending ? (
          <Skeleton className="h-40" />
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2" aria-label="Templates">
            {(templates.data ?? []).map((t) => (
              <li key={t.key}>
                <button
                  type="button"
                  aria-pressed={template === t.key}
                  onClick={() => setTemplate(t.key)}
                  className={cn(
                    'flex h-full w-full flex-col items-start gap-1 rounded-lg border p-3 text-left',
                    template === t.key ? 'border-ink bg-surface-2' : 'border-hairline hover:bg-surface-2',
                  )}
                >
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <Icon icon={LayoutDashboard} size={14} className="text-muted" aria-hidden />
                    {t.name}
                  </span>
                  <span className="text-xs text-muted">{t.description}</span>
                  <span className="text-xs text-muted-2">{t.widgets.length} widgets</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-3 px-5 py-4">
        {fixedPortfolio ? null : (
          <div>
            <label htmlFor="template-portfolio" className="mb-1 block text-xs font-medium text-muted">
              Portfolio
            </label>
            <select
              id="template-portfolio"
              value={portfolio}
              onChange={(e) => setPortfolio(e.target.value)}
              className="h-8 w-full rounded-md border border-hairline bg-surface px-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus/25"
            >
              <option value="">Pick a portfolio</option>
              {(portfolios.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {!template ? (
          <p className="py-10 text-center text-sm text-muted">Pick a template to see what it holds.</p>
        ) : !portfolio ? (
          <p className="py-10 text-center text-sm text-muted">Pick the portfolio it reads.</p>
        ) : preview.isPending ? (
          <Skeleton className="h-48" />
        ) : preview.isError ? (
          <p role="alert" className="py-6 text-sm text-muted">
            {(preview.error as { detail?: string }).detail ?? 'This template doesn’t fit this portfolio.'}
          </p>
        ) : (
          <section aria-label="What it will hold" className="space-y-3">
            <h3 className="text-sm font-semibold">{preview.data.name}</h3>
            <ol className="space-y-1 text-sm">
              {preview.data.widgets.map((w) => (
                <li key={w.title} className="flex items-baseline gap-2">
                  <span className="w-24 shrink-0 text-xs text-muted">{ANY_KIND_LABELS[w.kind]}</span>
                  <span>{w.title}</span>
                </li>
              ))}
            </ol>
            {preview.data.notes.length ? (
              <div className="rounded-md bg-surface-2 px-3 py-2 text-xs text-ink-2">
                <p className="mb-1 flex items-center gap-1.5 font-medium">
                  <Icon icon={AlertTriangle} size={12} className="text-warn" aria-hidden /> Left out
                </p>
                <ul className="list-disc space-y-0.5 pl-4">
                  {preview.data.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="text" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!template || !portfolio || !preview.data}
            loading={create.isPending}
            onClick={() =>
              create.mutate(
                { template: template!, portfolio_id: portfolio, portfolio_tab: portfolioTab },
                { onSuccess: (res) => onCreated(res.data.dashboard) },
              )
            }
          >
            Create dashboard
          </Button>
        </div>
      </div>
    </div>
  );
}
