import { http, HttpResponse } from 'msw';

type Att = {
  id: string;
  task_id: string | null;
  comment_id: string | null;
  filename: string;
  mime: string;
  size_bytes: number;
  sha256: string;
  extract_status: string;
  uploaded_by: string;
  created_at: string;
};

let n = 0;

/** In-memory S2.6.1 attachments API: task-scoped upload/list/delete. */
export function attachmentHandlers(base = '', initial: Att[] = []) {
  const rows: Att[] = [...initial];
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000f001', batch_id: null, version: 1 };

  return [
    http.get(`*${base}/api/v1/tasks/:tid/attachments`, ({ params }) =>
      HttpResponse.json({
        data: rows.filter((a) => a.task_id === params.tid),
        meta: { next_cursor: null },
      }),
    ),
    http.post(`*${base}/api/v1/tasks/:tid/attachments`, async ({ params, request }) => {
      const form = await request.formData();
      const file = form.get('file') as File;
      n += 1;
      const row: Att = {
        id: `att-${n}`,
        task_id: String(params.tid),
        comment_id: null,
        filename: file.name,
        mime: file.type || 'application/octet-stream',
        size_bytes: file.size,
        sha256: 'x'.repeat(64),
        extract_status: 'pending',
        uploaded_by: 'user-ravi',
        created_at: new Date().toISOString(),
      };
      rows.push(row);
      return HttpResponse.json({ data: row, meta }, { status: 201 });
    }),
    http.delete(`*${base}/api/v1/attachments/:id`, ({ params }) => {
      const i = rows.findIndex((a) => a.id === params.id);
      if (i >= 0) rows.splice(i, 1);
      return HttpResponse.json({ data: { ok: true }, meta });
    }),
  ];
}
