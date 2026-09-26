import { useMutation } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type CsvPreview = components['schemas']['CsvPreview'];
export type CsvImportResult = components['schemas']['CsvImportResult'];

/** Sent as a JSON-encoded `Form` field alongside the file (see `csv_import_router.py`), not a
 * JSON request body — openapi-typescript only generates a named schema for the latter, so this
 * type is hand-written to match `domain/tasks/csv_import.CsvColumnMapping` exactly. */
export interface CsvColumnMapping {
  title_col: string;
  section_col?: string;
  assignee_email_col?: string;
  due_on_col?: string;
  completed_col?: string;
}

export function useCsvPreview() {
  const api = useApi();
  return useMutation({
    mutationFn: async ({ projectId, file }: { projectId: string; file: File }) => {
      const body = new FormData();
      body.append('file', file);
      const res = await api.POST('/api/v1/projects/{project_id}/import/csv/preview', {
        params: { path: { project_id: projectId } },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        body: body as any,
      });
      return res.data!;
    },
    onError: (e) => toastError(e, "Couldn't read that CSV file"),
  });
}

export function useCsvCommit() {
  const api = useApi();
  return useMutation({
    mutationFn: async ({
      projectId,
      file,
      mapping,
    }: {
      projectId: string;
      file: File;
      mapping: CsvColumnMapping;
    }) => {
      const body = new FormData();
      body.append('file', file);
      body.append('mapping', JSON.stringify(mapping));
      const res = await api.POST('/api/v1/projects/{project_id}/import/csv', {
        params: { path: { project_id: projectId } },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        body: body as any,
      });
      return res.data!;
    },
    onError: (e) => toastError(e, "Couldn't import that CSV"),
  });
}
