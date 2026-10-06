import { http, HttpResponse } from 'msw';

type Question = {
  id: string;
  label: string;
  help_text?: string | null;
  required: boolean;
  maps_to: string;
  show_if?: { question_id: string; equals: unknown } | null;
};
type F = {
  id: string;
  project_id: string;
  section_id: string | null;
  name: string;
  description: string | null;
  questions: Question[];
  enabled: boolean;
  public_enabled: boolean;
  public_token: string;
  version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
};

/** In-memory S4.2.1 forms API: CRUD plus the public link's GET/submit, for component tests. */
export function formHandlers(base = '') {
  const forms: F[] = [];
  let n = 0;
  const now = '2026-09-27T00:00:00Z';

  return [
    http.get(`*${base}/api/v1/forms`, ({ request }) => {
      const url = new URL(request.url);
      const pid = url.searchParams.get('project_id');
      return HttpResponse.json({
        data: forms.filter((f) => f.project_id === pid),
        meta: { next_cursor: null },
      });
    }),
    http.post(`*${base}/api/v1/forms`, async ({ request }) => {
      const b = (await request.json()) as Omit<
        F,
        'id' | 'version' | 'created_by' | 'created_at' | 'updated_at' | 'public_token'
      >;
      const f: F = {
        ...b,
        id: `form-${++n}`,
        version: 1,
        created_by: 'user-1',
        created_at: now,
        updated_at: now,
        public_token: `tok-${n}`,
      };
      forms.push(f);
      return HttpResponse.json(
        { data: f, meta: { activity_id: null, batch_id: null, version: 1 } },
        { status: 201 },
      );
    }),
    http.get(`*${base}/api/v1/forms/:id`, ({ params }) => {
      const f = forms.find((x) => x.id === params.id);
      if (!f) return HttpResponse.json({ detail: 'not found' }, { status: 404 });
      return HttpResponse.json(f);
    }),
    http.patch(`*${base}/api/v1/forms/:id`, async ({ params, request }) => {
      const f = forms.find((x) => x.id === params.id)!;
      const b = (await request.json()) as Partial<F>;
      Object.assign(f, b);
      f.version += 1;
      return HttpResponse.json({ data: f, meta: { activity_id: null, batch_id: null, version: f.version } });
    }),
    http.delete(`*${base}/api/v1/forms/:id`, ({ params }) => {
      const i = forms.findIndex((f) => f.id === params.id);
      if (i >= 0) forms.splice(i, 1);
      return HttpResponse.json({ data: { ok: true }, meta: { activity_id: null } });
    }),
    http.post(`*${base}/api/v1/forms/:id/submit`, () => HttpResponse.json({ ok: true })),
    http.get(`*${base}/api/v1/public/forms/:token`, ({ params }) => {
      const f = forms.find((x) => x.public_token === params.token && x.public_enabled);
      if (!f) return HttpResponse.json({ detail: 'not found' }, { status: 404 });
      return HttpResponse.json({
        name: f.name,
        description: f.description,
        questions: f.questions.map((q) => ({
          id: q.id,
          label: q.label,
          help_text: q.help_text ?? null,
          required: q.required,
          kind: q.maps_to === 'description' ? 'long_text' : q.maps_to === 'due_on' ? 'date' : 'short_text',
          options: null,
          people: null,
          show_if: q.show_if ?? null,
        })),
      });
    }),
    http.post(`*${base}/api/v1/public/forms/:token/submit`, ({ params }) => {
      const f = forms.find((x) => x.public_token === params.token && x.public_enabled);
      if (!f) return HttpResponse.json({ detail: 'not found' }, { status: 404 });
      return HttpResponse.json({ ok: true }, { status: 201 });
    }),
  ];
}
