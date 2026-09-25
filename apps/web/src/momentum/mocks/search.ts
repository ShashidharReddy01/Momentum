import { http, HttpResponse } from 'msw';

type Results = {
  tasks: {
    id: string;
    title: string;
    type: string;
    completed_at: string | null;
    project_id: string | null;
    project_name: string | null;
  }[];
  projects: { id: string; name: string; color: string | null }[];
  people: { id: string; name: string; email: string; avatar_url: string | null }[];
  comments: { id: string; task_id: string; task_title: string; snippet: string }[];
};

const EMPTY: Results = { tasks: [], projects: [], people: [], comments: [] };

/** In-memory S2.6.2 search API. `byQuery` maps a lowercased query string to the unfiltered
 * results it should return (anything else returns an empty set, matching the real backend's "no
 * results" shape). The `type` query param is honored (filtering down to the requested
 * categories), mirroring the one piece of filtering the frontend tests actually exercise —
 * project/assignee/completed aren't applied here, since no test in this repo depends on that. */
export function searchHandlers(base = '', byQuery: Record<string, Results> = {}) {
  return [
    http.get(`*${base}/api/v1/search`, ({ request }) => {
      const url = new URL(request.url);
      const q = (url.searchParams.get('q') ?? '').toLowerCase();
      const result = byQuery[q] ?? EMPTY;
      const type = url.searchParams.get('type');
      if (!type) return HttpResponse.json(result);
      const wanted = new Set(type.split(','));
      return HttpResponse.json({
        tasks: wanted.has('task') ? result.tasks : [],
        projects: wanted.has('project') ? result.projects : [],
        people: wanted.has('person') ? result.people : [],
        comments: wanted.has('comment') ? result.comments : [],
      });
    }),
  ];
}
