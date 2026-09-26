import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { ApiError } from '@/lib/api/errors';
import { useMomentumConfig } from '@/lib/config';
import { postSse } from '@/lib/sse';

export interface MoToolStep {
  id: string;
  name: string;
  ok?: boolean;
  summary?: string;
  preview?: boolean;
}

export interface Candidate {
  key?: string;
  title?: string;
  project?: string;
  name?: string;
}

export interface MoRun {
  id: string;
  text: string;
  status: 'running' | 'done' | 'error';
  steps: MoToolStep[];
  reply: string;
  actionId: string | null;
  autoApplied: boolean;
  clarify: { question: string; candidates: Candidate[] } | null;
  error: string | null;
}

/** What the user is looking at, from the route (sent as context; the server re-checks access).
 * Selected rows aren't included yet: selection state is local to each list view. */
export function useScreen(): { kind: string; project_id?: string; task_id?: string; view?: string } {
  const path = useLocation().pathname;
  const project = /^\/projects\/([^/]+)(?:\/([^/]+))?/.exec(path);
  if (project)
    return { kind: 'project', project_id: project[1], ...(project[2] ? { view: project[2] } : {}) };
  const task = /^\/task\/([^/]+)/.exec(path);
  if (task) return { kind: 'task', task_id: task[1] };
  if (path === '/my-tasks') return { kind: 'my_tasks' };
  if (path === '/inbox') return { kind: 'inbox' };
  if (path === '/search') return { kind: 'search' };
  if (path === '/') return { kind: 'home' };
  return { kind: 'other' };
}

const TOOL_WORDS: Record<string, string> = {
  search_tasks: 'Searched tasks',
  semantic_search: 'Searched content',
  get_task: 'Read a task',
  get_project: 'Read a project',
  get_section_tasks: 'Read a section',
  list_my_tasks: 'Read your tasks',
  list_user_tasks: "Read someone's tasks",
  get_project_activity: 'Read project activity',
  list_people: 'Looked up people',
};

/** "Searched tasks · Previewed bulk update tasks" for the compact activity line. */
export function describeStep(s: MoToolStep): string {
  return TOOL_WORDS[s.name] ?? `Previewed ${s.name.replaceAll('_', ' ')}`;
}

/** ⌘K commands run through `POST /ai/command` (S3.2.2), streamed into the Ask Mo panel. */
export function useMoRuns() {
  const config = useMomentumConfig();
  const qc = useQueryClient();
  const screen = useScreen();
  const [runs, setRuns] = useState<MoRun[]>([]);
  const screenRef = useRef(screen);
  screenRef.current = screen;

  const update = (id: string, fn: (r: MoRun) => MoRun) =>
    setRuns((rs) => rs.map((r) => (r.id === id ? fn(r) : r)));

  const run = useCallback(
    async (text: string) => {
      const id = `${Date.now()}-${Math.random()}`;
      setRuns((rs) => [
        ...rs,
        {
          id,
          text,
          status: 'running',
          steps: [],
          reply: '',
          actionId: null,
          autoApplied: false,
          clarify: null,
          error: null,
        },
      ]);
      try {
        await postSse(
          `${config.api_base}/ai/command`,
          { text, screen: screenRef.current },
          ({ event, data }) => {
            switch (event) {
              case 'tool_call':
                update(id, (r) => ({
                  ...r,
                  steps: [...r.steps, { id: String(data.id), name: String(data.name) }],
                }));
                break;
              case 'tool_result':
                update(id, (r) => ({
                  ...r,
                  steps: r.steps.map((s) =>
                    s.id === data.id
                      ? {
                          ...s,
                          ok: Boolean(data.ok),
                          summary: String(data.summary ?? ''),
                          preview: Boolean(data.preview),
                        }
                      : s,
                  ),
                }));
                break;
              case 'token':
                update(id, (r) => ({ ...r, reply: r.reply + String(data.text ?? '') }));
                break;
              case 'action_proposed':
                update(id, (r) => ({ ...r, actionId: String(data.action_id) }));
                break;
              case 'action_applied':
                update(id, (r) => ({ ...r, autoApplied: true }));
                void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'ai' });
                break;
              case 'clarify':
                update(id, (r) => ({
                  ...r,
                  clarify: {
                    question: String(data.question ?? ''),
                    candidates: (data.candidates as Candidate[]) ?? [],
                  },
                }));
                break;
              case 'error':
                update(id, (r) => ({
                  ...r,
                  status: 'error',
                  error: String(data.message ?? 'Something went wrong'),
                }));
                break;
              case 'done':
                update(id, (r) => ({ ...r, status: r.status === 'error' ? 'error' : 'done' }));
                break;
            }
          },
        );
        update(id, (r) => (r.status === 'running' ? { ...r, status: 'done' } : r));
      } catch (e) {
        const message =
          e instanceof ApiError
            ? (e.problem.detail ?? e.problem.title ?? 'Something went wrong')
            : 'Something went wrong';
        update(id, (r) => ({ ...r, status: 'error', error: message }));
      }
    },
    [config.api_base, qc],
  );

  return { runs, run };
}
