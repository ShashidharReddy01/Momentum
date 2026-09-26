import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { ApiError } from '@/lib/api/errors';
import { useMomentumConfig } from '@/lib/config';
import type { components } from '@/lib/api/schema';
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

/** A `[T-12]` / `[P:Name]` reference in Mo's answer, resolved by the server as the reader:
 * only `valid` ones (it exists and you can see it) become links. */
export interface Citation {
  ref: string;
  type: 'task' | 'project';
  valid: boolean;
  id?: string | null;
  key?: string | null;
  title?: string | null;
}

export interface MoRun {
  id: string;
  /** `command`: ⌘K (S3.2.2); `chat`: a question to Ask Mo (S3.3.1). */
  kind: 'command' | 'chat';
  text: string;
  status: 'running' | 'done' | 'error';
  steps: MoToolStep[];
  reply: string;
  actionId: string | null;
  autoApplied: boolean;
  clarify: { question: string; candidates: Candidate[] } | null;
  error: string | null;
  citations: Citation[];
  /** Mo's stored message (chat), for 👍/👎. */
  messageId: string | null;
  /** false: the answer cites nothing in the workspace. */
  grounded: boolean | null;
  rating: -1 | 1 | null;
}

const newRun = (kind: MoRun['kind'], text: string, over: Partial<MoRun> = {}): MoRun => ({
  id: `${Date.now()}-${Math.random()}`,
  kind,
  text,
  status: 'running',
  steps: [],
  reply: '',
  actionId: null,
  autoApplied: false,
  clarify: null,
  error: null,
  citations: [],
  messageId: null,
  grounded: null,
  rating: null,
  ...over,
});

type ChatMessage = components['schemas']['ChatMessageOut'];

/** A stored conversation as runs: each question with the answer that followed it. */
export function runsFromMessages(messages: ChatMessage[]): MoRun[] {
  const runs: MoRun[] = [];
  for (const m of messages) {
    if (m.role === 'user') {
      runs.push(
        newRun('chat', m.text, {
          id: m.id,
          status: 'error',
          error: 'No answer was saved for this message.',
        }),
      );
      continue;
    }
    const q = runs.at(-1);
    if (!q || q.status !== 'error' || q.reply) continue;
    Object.assign(q, {
      status: 'done',
      error: null,
      reply: m.text,
      steps: (m.steps ?? []).map((s, i) => ({ id: String(i), name: s.name, ok: s.ok ?? undefined })),
      citations: m.citations ?? [],
      actionId: m.action_id ?? null,
      clarify: m.candidates?.length ? { question: m.text, candidates: m.candidates as Candidate[] } : null,
      messageId: m.id,
      grounded: m.grounded ?? null,
      rating: m.rating ?? null,
    } satisfies Partial<MoRun>);
  }
  return runs;
}

/** What the user is looking at, from the route (sent as context; the server re-checks access).
 * Selected rows aren't included yet: selection state is local to each list view. */
export interface Screen {
  kind: string;
  project_id?: string;
  task_id?: string;
  view?: string;
  selected_task_ids?: string[];
}

export function useScreen(): Screen {
  const { pathname: path, search } = useLocation();
  const paneTask = new URLSearchParams(search).get('task');
  const project = /^\/projects\/([^/]+)(?:\/([^/]+))?/.exec(path);
  if (project)
    return {
      kind: 'project',
      project_id: project[1],
      ...(project[2] ? { view: project[2] } : {}),
      ...(paneTask ? { task_id: paneTask } : {}),
    };
  const task = /^\/task\/([^/]+)/.exec(path);
  if (task) return { kind: 'task', task_id: task[1] };
  if (path === '/my-tasks') return { kind: 'my_tasks', ...(paneTask ? { task_id: paneTask } : {}) };
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

/**
 * Mo's runs in the Ask Mo panel and on `/ask`: ⌘K commands (`POST /ai/command`, S3.2.2) and
 * chat questions (`POST /ai/chat`, S3.3.1), both streamed. Questions continue one conversation
 * until `newChat()`; `open(id, runs)` shows a stored one. `screen` (S3.3.2: a pinned "Ask Mo
 * about this" context) replaces the one read from the route.
 */
export function useMoRuns(opts: { screen?: Screen | null } = {}) {
  const config = useMomentumConfig();
  const qc = useQueryClient();
  const routeScreen = useScreen();
  const screen = opts.screen ?? routeScreen;
  const [runs, setRuns] = useState<MoRun[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const convRef = useRef(conversationId);
  convRef.current = conversationId;

  const update = (id: string, fn: (r: MoRun) => MoRun) =>
    setRuns((rs) => rs.map((r) => (r.id === id ? fn(r) : r)));

  const start = useCallback(
    async (kind: MoRun['kind'], text: string) => {
      const run = newRun(kind, text);
      const id = run.id;
      setRuns((rs) => [...rs, run]);
      const url = `${config.api_base}/ai/${kind === 'chat' ? 'chat' : 'command'}`;
      const body =
        kind === 'chat'
          ? { text, screen: screenRef.current, conversation_id: convRef.current }
          : { text, screen: screenRef.current };
      try {
        await postSse(url, body, ({ event, data }) => {
          switch (event) {
            case 'conversation':
              convRef.current = String(data.conversation_id);
              setConversationId(convRef.current);
              void qc.invalidateQueries({ queryKey: ['ai', 'conversations'] });
              break;
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
            case 'citation':
              update(id, (r) => ({ ...r, citations: [...r.citations, data as unknown as Citation] }));
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
              if (kind === 'chat') void qc.invalidateQueries({ queryKey: ['ai', 'conversations'] });
              update(id, (r) => ({
                ...r,
                status: r.status === 'error' ? 'error' : 'done',
                messageId: data.message_id ? String(data.message_id) : r.messageId,
                grounded: typeof data.grounded === 'boolean' ? data.grounded : r.grounded,
              }));
              break;
          }
        });
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

  const run = useCallback((text: string) => start('command', text), [start]);
  const ask = useCallback((text: string) => start('chat', text), [start]);
  const newChat = useCallback(() => {
    convRef.current = null;
    setConversationId(null);
    setRuns([]);
  }, []);
  const open = useCallback((id: string, stored: MoRun[]) => {
    convRef.current = id;
    setConversationId(id);
    setRuns(stored);
  }, []);
  const rate = useCallback((runId: string, rating: -1 | 1) => update(runId, (r) => ({ ...r, rating })), []);

  return { runs, run, ask, newChat, open, rate, conversationId };
}
