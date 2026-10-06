import { http, HttpResponse } from 'msw';

export type MockFile = {
  id: string;
  filename: string;
  mime: string;
  kind: string;
  size_bytes: number;
  uploaded_by: string;
  uploaded_by_name: string;
  created_at: string;
  version: number;
  versions_count: number;
  version_group: string;
  source: string;
  ai_drafted: boolean;
  deleted?: boolean;
  location: {
    type: string;
    task_id?: string | null;
    task_key?: string | null;
    task_title?: string | null;
    comment_id?: string | null;
  };
};

const META = { activity_id: '01a0ccaf-0000-7000-8000-00000000f101', batch_id: null, version: 1 };
let n = 0;

function kindOf(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  if (['xlsx', 'xls', 'csv'].includes(ext)) return 'spreadsheet';
  if (['docx', 'doc'].includes(ext)) return 'document';
  if (ext === 'pdf') return 'pdf';
  if (['png', 'jpg', 'jpeg'].includes(ext)) return 'image';
  return 'text';
}

/** In-memory Phase 7.5 Files API: the project inventory, uploads with versions, delete. */
export function fileHandlers(initial: MockFile[] = []) {
  const rows: MockFile[] = [...initial];
  const uploads: { name: string; replace_id: string | null }[] = [];
  const deleted: string[] = [];
  const current = () =>
    rows.filter(
      (r) =>
        !r.deleted &&
        rows.every((o) => o.deleted || o.version_group !== r.version_group || o.version <= r.version),
    );
  return {
    uploads,
    deleted,
    rows,
    handlers: [
      http.get('*/api/v1/projects/:pid/files', ({ request }) => {
        const url = new URL(request.url);
        const q = url.searchParams.get('q')?.toLowerCase();
        const kind = url.searchParams.get('kind');
        const data = current()
          .filter((r) => !q || r.filename.toLowerCase().includes(q))
          .filter((r) => !kind || r.kind === kind)
          .map((r) => ({
            ...r,
            versions_count: rows.filter((o) => !o.deleted && o.version_group === r.version_group).length,
          }));
        return HttpResponse.json({ data, next_cursor: null, total: data.length });
      }),
      http.post('*/api/v1/projects/:pid/files', async ({ request }) => {
        const form = await request.formData();
        // tests send a URL-encoded stand-in (jsdom's File can't cross MSW): the name only
        const raw = form.get('file');
        const file = typeof raw === 'string' ? { name: raw, type: '', size: 1 } : (raw as File);
        const replace = (form.get('replace_id') as string | null) || null;
        uploads.push({ name: file.name, replace_id: replace });
        n += 1;
        const prev = replace ? rows.find((r) => r.id === replace) : undefined;
        const group = prev ? prev.version_group : `file-new-${n}`;
        const version = prev
          ? Math.max(...rows.filter((r) => r.version_group === group).map((r) => r.version)) + 1
          : 1;
        const row: MockFile = {
          id: prev ? `file-new-${n}` : group,
          filename: file.name,
          mime: file.type || 'text/plain',
          kind: kindOf(file.name),
          size_bytes: file.size,
          uploaded_by: 'user-ravi',
          uploaded_by_name: 'Ravi Kumar',
          created_at: new Date().toISOString(),
          version,
          versions_count: version,
          version_group: group,
          source: 'upload',
          ai_drafted: false,
          location: { type: 'project' },
        };
        rows.push(row);
        return HttpResponse.json(
          { data: { ...row, task_id: null, comment_id: null }, meta: META },
          { status: 201 },
        );
      }),
      http.get('*/api/v1/attachments/:id/versions', ({ params }) => {
        const target = rows.find((r) => r.id === params.id);
        const data = rows
          .filter((r) => !r.deleted && r.version_group === target?.version_group)
          .sort((a, b) => b.version - a.version)
          .map((r, i) => ({
            ...r,
            task_id: null,
            comment_id: null,
            sha256: 'x',
            extract_status: 'done',
            is_current: i === 0,
          }));
        return HttpResponse.json({ data, meta: { next_cursor: null } });
      }),
      http.delete('*/api/v1/attachments/:id', ({ params }) => {
        const r = rows.find((x) => x.id === params.id);
        if (r) r.deleted = true;
        deleted.push(String(params.id));
        return HttpResponse.json({ data: { ok: true }, meta: META });
      }),
    ],
  };
}

const MIME: Record<string, string> = {
  spreadsheet: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  document: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pdf: 'application/pdf',
  image: 'image/png',
  text: 'text/plain',
};

export function mockFile(over: Partial<MockFile> & { id: string; filename: string }): MockFile {
  return {
    mime: MIME[kindOf(over.filename)] ?? 'application/octet-stream',
    kind: kindOf(over.filename),
    size_bytes: 1200,
    uploaded_by: 'user-ravi',
    uploaded_by_name: 'Ravi Kumar',
    created_at: '2026-10-01T10:00:00Z',
    version: 1,
    versions_count: 1,
    version_group: over.id,
    source: 'upload',
    ai_drafted: false,
    location: { type: 'project' },
    ...over,
  };
}
