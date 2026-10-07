import { Download, FileText, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatRelative } from '@/lib/dates';
import { useUndoToast } from '@/lib/undo';
import { KINDS, usePortfolioFiles, useRegenerate, type ReportKind } from './queries';
import { ReportDialog } from './ReportDialog';

/**
 * Phase 7.5 (spec §6.3): a portfolio's Reports tab. The reports made for it (portfolio status,
 * task exports, its dashboard), newest first: download, regenerate (a new version), the
 * AI-drafted badge when Mo wrote part of it.
 */
export function PortfolioReports({
  portfolioId,
  portfolioName,
  canEdit,
}: {
  portfolioId: string;
  portfolioName: string;
  canEdit: boolean;
}) {
  const files = usePortfolioFiles(portfolioId);
  const regenerate = useRegenerate();
  const undoToast = useUndoToast();
  const [open, setOpen] = useState(false);

  if (files.isPending) return <Skeleton className="h-40" />;
  if (files.isError) return <ErrorState error={files.error} onRetry={() => void files.refetch()} />;
  const create = canEdit ? (
    <Button variant="primary" onClick={() => setOpen(true)}>
      <Icon icon={FileText} size={15} /> Create report
    </Button>
  ) : null;
  return (
    <div className="space-y-3">
      {files.data.length === 0 ? (
        <EmptyState icon={FileText} title="No reports yet" action={create}>
          Make a portfolio status report (Word, PDF or Excel) or a task export from what this portfolio holds.
          It’s built from the numbers you see, and kept here.
        </EmptyState>
      ) : (
        <>
          <div className="flex justify-end">{create}</div>
          <ul
            aria-label="Reports"
            className="divide-y divide-hair-soft rounded-xl border border-hair-soft bg-surface"
          >
            {files.data.map((f) => {
              const spec = (f.generated_spec ?? {}) as { kind?: ReportKind; ai_drafted?: boolean };
              return (
                <li key={f.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <Icon icon={FileText} size={16} className="text-muted" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{f.filename}</span>
                    <span className="text-xs text-muted">
                      {spec.kind ? KINDS[spec.kind].label : 'File'} · {formatRelative(f.created_at)}
                      {f.version > 1 ? ` · v${f.version}` : ''}
                    </span>
                  </span>
                  {spec.ai_drafted ? (
                    <span
                      className="rounded border border-amber/50 px-1 text-[11px] text-amber-ink"
                      title="Contains AI-drafted text: review before sending"
                    >
                      AI-drafted
                    </span>
                  ) : null}
                  <a
                    href={`/api/v1/attachments/${f.id}/download`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-sm hover:bg-surface-2"
                  >
                    <Icon icon={Download} size={14} /> Download
                  </a>
                  {canEdit && f.source === 'generated' ? (
                    <Button
                      variant="text"
                      loading={regenerate.isPending && regenerate.variables === f.id}
                      onClick={() =>
                        regenerate.mutate(f.id, {
                          onSuccess: (r) =>
                            r.status === 'done'
                              ? undoToast(`Regenerated: ${r.filename ?? f.filename}`, {
                                  activity_id: r.activity_id ?? null,
                                })
                              : undefined,
                        })
                      }
                    >
                      <Icon icon={RefreshCw} size={14} /> Regenerate
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}
      {open ? (
        <ReportDialog open onOpenChange={setOpen} scope={{ portfolioId }} name={portfolioName} />
      ) : null}
    </div>
  );
}
