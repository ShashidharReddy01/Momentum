import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { AskFilters, errorText, type FilterDraft } from '@/features/ai';
import { usePostStatus } from '@/features/status';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';
import { portfolioKeys, usePortfolioMutations } from './queries';
import type { ViewFilters } from './v2queries';

/** Phase 7.5 S75-10 (spec §8): Mo on a portfolio, all on request. Every answer is a preview:
 * a brief or a handoff posts as a status update only after the person confirms; filters apply
 * only on Apply. Mo's text carries the amber mark. */

export type Brief = components['schemas']['BriefOut'];
export type { FilterDraft };
export type ReadinessCheck = components['schemas']['ReadinessCheckOut'];
export type Handoff = components['schemas']['HandoffOut'];
type StatusUpdateIn = components['schemas']['StatusUpdateIn'];

const BRIEF_KIND: Record<string, string> = {
  slipping: 'Slipping',
  sla: 'Over stage target',
  bottleneck: 'Bottleneck',
  waiting_customer: 'Waiting on the customer',
  waiting_us: 'Waiting on us',
  decision: 'Needs a decision',
};
const HANDOFF_TITLES: Record<string, string> = {
  sold: 'What was sold',
  scope: 'Scope',
  out_of_scope: 'Out of scope',
  commitments: 'Commitments and dates',
  contacts: 'Contacts',
  risks: 'Open risks',
  waiting: 'Waiting on',
};

function useAiPost<T>(run: (api: ReturnType<typeof useApi>) => Promise<T>) {
  const api = useApi();
  return useMutation({ mutationFn: () => run(api) });
}

function AiError({ error }: { error: unknown }) {
  return (
    <p role="alert" className="text-sm text-crit">
      {errorText(error)}
    </p>
  );
}

/** A status update preview the person reads before posting it (generated_by_ai stays set). */
function StatusPreview({ draft }: { draft: StatusUpdateIn }) {
  const s = draft.sections;
  const lists: [string, { text: string }[] | undefined][] = [
    ['Completed', s?.completed],
    ['Slipped', s?.slipped],
    ['Blockers', s?.blockers],
    ['Next', s?.next],
  ];
  return (
    <section
      aria-label="Status update preview"
      className="space-y-2 rounded-md border border-hairline p-3 text-sm"
    >
      <p className="font-medium">{draft.title}</p>
      {draft.summary ? <p className="whitespace-pre-line text-ink-2">{draft.summary}</p> : null}
      {lists.map(([label, items]) =>
        items?.length ? (
          <div key={label}>
            <p className="text-xs font-medium text-muted">{label}</p>
            <ul className="list-disc pl-5">
              {items.map((i, n) => (
                <li key={n}>{i.text}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </section>
  );
}

// ---------------- Brief me ----------------

export function BriefButton({ portfolioId, portfolioName }: { portfolioId: string; portfolioName: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="ai" onClick={() => setOpen(true)}>
        <MoMark size={13} /> Brief me
      </Button>
      {open ? (
        <Dialog
          open
          onOpenChange={setOpen}
          title={`Brief: ${portfolioName}`}
          description="Mo's read of the portfolio, from its table and stage numbers. Nothing is saved."
          className="w-[min(640px,calc(100vw-32px))]"
        >
          <BriefBody portfolioId={portfolioId} onDone={() => setOpen(false)} />
        </Dialog>
      ) : null}
    </>
  );
}

function BriefBody({ portfolioId, onDone }: { portfolioId: string; onDone: () => void }) {
  const brief = useAiPost(async (api) => {
    const r = await api.POST('/api/v1/ai/portfolios/{portfolio_id}/brief', {
      params: { path: { portfolio_id: portfolioId } },
    });
    return r.data!;
  });
  const { postStatus } = usePortfolioMutations(portfolioId);
  const [preview, setPreview] = useState(false);
  const run = brief.mutate;
  useEffect(() => run(), [run]);
  if (brief.isIdle || brief.isPending) return <Skeleton className="m-5 h-40" />;
  if (brief.isError)
    return (
      <div className="p-5">
        <AiError error={brief.error} />
      </div>
    );
  const b = brief.data!;
  return (
    <div className="space-y-4 p-5">
      <p className="flex items-start gap-2 text-sm font-medium">
        {b.ai ? <MoMark size={14} className="mt-0.5 shrink-0" /> : null}
        <span className={b.ai ? 'text-amber-ink' : ''}>{b.headline}</span>
      </p>
      {b.items.length ? (
        <ul className="space-y-2" aria-label="Brief">
          {b.items.map((i, n) => (
            <li key={n} className="text-sm">
              <span className="mr-1.5 text-xs font-medium text-muted">{BRIEF_KIND[i.kind] ?? i.kind}</span>
              <span className="text-amber-ink">{i.text}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {b.hidden ? (
        <p className="text-xs text-muted">
          {b.hidden} {b.hidden === 1 ? 'project' : 'projects'} in this portfolio you can’t see{' '}
          {b.hidden === 1 ? 'isn’t' : 'aren’t'} included.
        </p>
      ) : null}
      {preview ? <StatusPreview draft={b.status_update} /> : null}
      <div className="flex justify-end gap-2">
        <Button variant="text" onClick={onDone}>
          Done
        </Button>
        {b.ai && b.items.length ? (
          preview ? (
            <Button
              variant="primary"
              loading={postStatus.isPending}
              onClick={() => postStatus.mutate(b.status_update, { onSuccess: onDone })}
            >
              Post status update
            </Button>
          ) : (
            <Button onClick={() => setPreview(true)}>Post as status update…</Button>
          )
        ) : null}
      </div>
    </div>
  );
}

// ---------------- Ask the portfolio (plain-English filters) ----------------

export function AskPortfolio({
  portfolioId,
  applied,
  onApply,
}: {
  portfolioId: string;
  applied: FilterDraft | null;
  onApply: (d: FilterDraft | null) => void;
}) {
  return (
    <AskFilters
      surface="portfolio"
      portfolioId={portfolioId}
      applied={applied}
      onApply={onApply}
      onClear={() => onApply(null)}
      label="Ask the portfolio"
    />
  );
}

export function draftFilters(d: FilterDraft | null): Partial<ViewFilters> | null {
  return d ? (d.filters as Partial<ViewFilters>) : null;
}

// ---------------- Readiness check: Mo reads the gate's files ----------------

export function ReadWithMo({
  portfolioId,
  projectId,
  to,
}: {
  portfolioId: string;
  projectId: string;
  to: string;
}) {
  const api = useApi();
  const [readFiles, setReadFiles] = useState(false);
  const check = useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/ai/portfolios/{portfolio_id}/projects/{project_id}/readiness', {
          params: { path: { portfolio_id: portfolioId, project_id: projectId } },
          body: { to, read_files: readFiles },
        })
      ).data!,
  });
  const r = check.data;
  return (
    <section aria-label="Check with Mo" className="space-y-2 rounded-md bg-surface-2 p-3">
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={readFiles} onChange={(e) => setReadFiles(e.target.checked)} />
        Also let Mo read the files
      </label>
      <Button
        size="sm"
        variant="ai"
        onClick={() => check.mutate()}
        loading={check.isPending}
        disabled={!readFiles}
      >
        <MoMark size={12} /> Check the files
      </Button>
      {check.isError ? <AiError error={check.error} /> : null}
      {r ? (
        r.notes.length ? (
          <ul className="space-y-1" aria-label="Mo's notes">
            {r.notes.map((n, i) => (
              <li key={i} className="flex items-start gap-1.5 text-sm text-amber-ink">
                {n.concern ? (
                  <Icon
                    icon={AlertTriangle}
                    size={14}
                    className="mt-0.5 shrink-0 text-warn"
                    aria-label="Concern"
                  />
                ) : (
                  <MoMark size={12} className="mt-1 shrink-0" />
                )}
                {n.text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">
            {r.files_read.length
              ? 'Mo had nothing to add about the files.'
              : 'There are no gate files to read yet.'}
          </p>
        )
      ) : null}
      {r?.unreadable.length ? (
        <p className="text-xs text-muted">Couldn’t read: {r.unreadable.join(', ')}</p>
      ) : null}
    </section>
  );
}

/** "Check readiness for <stage>" from a card's menu: the gate's checklist (no AI), then Mo's
 * notes on its files when asked. */
export function ReadinessDialog({
  portfolioId,
  project,
  stage,
  onClose,
}: {
  portfolioId: string;
  project: { id: string; name: string };
  stage: { id: string; label: string };
  onClose: () => void;
}) {
  const check = useAiPost(async (api) => {
    const r = await api.POST('/api/v1/ai/portfolios/{portfolio_id}/projects/{project_id}/readiness', {
      params: { path: { portfolio_id: portfolioId, project_id: project.id } },
      body: { to: stage.id, read_files: false },
    });
    return r.data!;
  });
  const run = check.mutate;
  useEffect(() => run(), [run]);
  const r = check.data?.readiness;
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Readiness of ${project.name} for ${stage.label}`}
    >
      <div className="space-y-4 p-5">
        {check.isError ? <AiError error={check.error} /> : null}
        {!r ? (
          check.isError ? null : (
            <Skeleton className="h-24" />
          )
        ) : r.items.length ? (
          <>
            <p className="text-sm">{r.met ? 'Everything the gate needs is there.' : 'Not ready yet.'}</p>
            <ul className="space-y-1.5" aria-label="Gate checklist">
              {r.items.map((i) => (
                <li key={`${i.kind}:${i.label}`} className="flex items-center gap-2 text-sm">
                  <Icon
                    icon={i.met ? Check : X}
                    size={14}
                    className={i.met ? 'text-ok' : 'text-crit'}
                    aria-label={i.met ? 'Met' : 'Missing'}
                  />
                  <span className="text-muted">{i.kind}</span>
                  <span>{i.label}</span>
                </li>
              ))}
            </ul>
            {r.items.some((i) => i.kind === 'file') ? (
              <ReadWithMo portfolioId={portfolioId} projectId={project.id} to={stage.id} />
            ) : null}
          </>
        ) : (
          <p className="text-sm text-muted">{stage.label} has no gate: any project can move into it.</p>
        )}
        <div className="flex justify-end">
          <Button variant="text" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------- Handoff note ----------------

export function HandoffDialog({
  project,
  stage,
  onClose,
}: {
  project: { id: string; name: string };
  stage: string | null;
  onClose: () => void;
}) {
  const api = useApi();
  const qc = useQueryClient();
  const [readFiles, setReadFiles] = useState(false);
  const draft = useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/ai/projects/{project_id}/handoff', {
          params: { path: { project_id: project.id } },
          body: { to_stage: stage, read_files: readFiles },
        })
      ).data!,
  });
  const post = usePostStatus(project.id);
  const h = draft.data;
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Draft handoff${stage ? ` to ${stage}` : ''}: ${project.name}`}
      description="Mo writes it from the project's brief, fields, milestones, open work and comments. Nothing is posted until you confirm."
      className="w-[min(680px,calc(100vw-32px))]"
    >
      <div className="max-h-[70vh] space-y-4 overflow-auto p-5">
        {!h ? (
          <>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={readFiles} onChange={(e) => setReadFiles(e.target.checked)} />
              Also let Mo read the project’s latest files
            </label>
            {draft.isError ? <AiError error={draft.error} /> : null}
            <div className="flex justify-end gap-2">
              <Button variant="text" onClick={onClose}>
                Cancel
              </Button>
              <Button variant="ai" loading={draft.isPending} onClick={() => draft.mutate()}>
                <MoMark size={12} /> Draft handoff
              </Button>
            </div>
          </>
        ) : (
          <>
            {Object.keys(h.sections).length ? (
              <div className="space-y-3" aria-label="Handoff note">
                {Object.entries(h.sections).map(([key, items]) => (
                  <div key={key}>
                    <p className="text-xs font-medium text-muted">{HANDOFF_TITLES[key] ?? key}</p>
                    <ul className="list-disc pl-5 text-sm text-amber-ink">
                      {items.map((i, n) => (
                        <li key={n}>{i.text}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">Mo found nothing it could back with the project’s facts.</p>
            )}
            <StatusPreview draft={h.status_update} />
            <div className="flex justify-end gap-2">
              <Button variant="text" onClick={onClose}>
                Discard
              </Button>
              <Button
                variant="primary"
                loading={post.isPending}
                disabled={!Object.keys(h.sections).length}
                onClick={() =>
                  post.mutate(h.status_update, {
                    onSuccess: () => {
                      void qc.invalidateQueries({ queryKey: portfolioKeys.all });
                      onClose();
                    },
                  })
                }
              >
                Post as status update
              </Button>
            </div>
          </>
        )}
      </div>
    </Dialog>
  );
}

/** After a stage move: offer the handoff (never written on its own). */
export function HandoffOffer({
  project,
  stage,
  onDismiss,
}: {
  project: { id: string; name: string };
  stage: string;
  onDismiss: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-2 rounded-md bg-surface-2 px-3 py-2 text-sm"
    >
      <span>
        Moved{' '}
        <Link to={`/projects/${project.id}/overview`} className="font-medium hover:underline">
          {project.name}
        </Link>{' '}
        to {stage}.
      </span>
      <Button size="sm" variant="ai" onClick={() => setOpen(true)}>
        <MoMark size={12} /> Draft handoff to {stage}
      </Button>
      <Button size="sm" variant="text" onClick={onDismiss}>
        Dismiss
      </Button>
      {open ? (
        <HandoffDialog
          project={project}
          stage={stage}
          onClose={() => {
            setOpen(false);
            onDismiss();
          }}
        />
      ) : null}
    </div>
  );
}
