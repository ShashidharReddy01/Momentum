import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type ReportSpec = components['schemas']['ReportSpec'];
export type ReportKind = ReportSpec['kind'];
export type ReportFormat = ReportSpec['format'];
export type ReportPreview = components['schemas']['ReportPreviewOut'];
export type ReportRun = components['schemas']['ReportRunOut'];

/** spec §6.2: what each kind is about and which formats it renders (the server checks again). */
export const KINDS: Record<ReportKind, { label: string; formats: ReportFormat[]; hint: string }> = {
  project_status: {
    label: 'Status report',
    formats: ['docx', 'pdf', 'md'],
    hint: 'Progress, milestones, what’s late and next',
  },
  customer_status: {
    label: 'Customer update',
    formats: ['docx', 'pdf'],
    hint: 'Safe to send: no internal work or names',
  },
  closeout: { label: 'Close-out', formats: ['docx', 'pdf'], hint: 'Planned vs actual, slips, lessons' },
  portfolio_status: {
    label: 'Portfolio status',
    formats: ['docx', 'pdf', 'xlsx'],
    hint: 'Stages, at-risk, go-lives, slipping',
  },
  task_export: { label: 'Task export', formats: ['xlsx', 'csv'], hint: 'Every task with its fields' },
  dashboard: { label: 'Dashboard', formats: ['pdf', 'docx'], hint: 'Each chart with its numbers' },
  // Phase 7.6: offered from the Records tab (S76-08), with its record type
  records_export: { label: 'Records export', formats: ['xlsx', 'csv'], hint: 'Every record with its lines' },
};
export const FORMAT_LABELS: Record<ReportFormat, string> = {
  docx: 'Word',
  pdf: 'PDF',
  xlsx: 'Excel',
  md: 'Markdown',
  csv: 'CSV',
};
export const NARRATIVE_KINDS: ReportKind[] = [
  'project_status',
  'customer_status',
  'closeout',
  'portfolio_status',
];

export const reportKeys = {
  preview: (spec: ReportSpec) => ['reports', 'preview', spec] as const,
  job: (id: string) => ['reports', 'job', id] as const,
};

export function useReportPreview(spec: ReportSpec | null) {
  const api = useApi();
  return useQuery({
    queryKey: reportKeys.preview(spec as ReportSpec),
    enabled: spec !== null,
    retry: false,
    placeholderData: keepPreviousData,
    queryFn: async () => (await api.POST('/api/v1/reports/preview', { body: { spec: spec! } })).data!,
  });
}

export function useCreateReport() {
  const api = useApi();
  return useMutation({
    mutationFn: async (spec: ReportSpec) => (await api.POST('/api/v1/reports', { body: { spec } })).data!,
    onError: (e) => toastError(e, "Couldn't make the report"),
  });
}

/** Poll a job until it is done or failed (a worker may take a moment). */
export function useReportJob(id: string | null, initial: ReportRun | null) {
  const api = useApi();
  const qc = useQueryClient();
  return useQuery({
    queryKey: reportKeys.job(id ?? ''),
    enabled: id !== null && initial !== null && (initial.status === 'queued' || initial.status === 'running'),
    initialData: initial ?? undefined,
    refetchInterval: (q) =>
      q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 1500 : false,
    queryFn: async () => {
      const run = (await api.GET('/api/v1/reports/jobs/{run_id}', { params: { path: { run_id: id! } } }))
        .data!;
      if (run.status === 'done') void qc.invalidateQueries({ queryKey: ['files'] });
      return run;
    },
  });
}

export type PortfolioFile = components['schemas']['AttachmentOut'];

export function usePortfolioFiles(portfolioId: string) {
  const api = useApi();
  return useQuery({
    queryKey: ['files', 'portfolio', portfolioId] as const,
    queryFn: async () =>
      (
        await api.GET('/api/v1/portfolios/{portfolio_id}/files', {
          params: { path: { portfolio_id: portfolioId } },
        })
      ).data!.data,
  });
}

/** Run a generated report's spec again: the result is the file's next version. */
export function useRegenerate() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (attachmentId: string) =>
      (
        await api.POST('/api/v1/attachments/{attachment_id}/regenerate', {
          params: { path: { attachment_id: attachmentId } },
        })
      ).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['files'] }),
    onError: (e) => toastError(e, "Couldn't regenerate the report"),
  });
}
