import { useQueryClient } from '@tanstack/react-query';
import type { JSONContent } from '@tiptap/react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api/errors';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';
import { syncTask, type TaskDetail } from '../detail';
import { taskKeys } from '../queries';

export type SaveState = 'saved' | 'dirty' | 'saving' | 'offline' | 'signed-out' | 'conflict' | 'error';

interface Draft {
  doc: JSONContent | null;
  base: string; // description_hash the draft started from
  at: number;
}

const SAVE_AFTER_MS = 800;
const DRAFT_AFTER_MS = 150;
const DRAFT_TTL_MS = 14 * 24 * 3600_000;
const RETRY_MS = [3_000, 10_000, 30_000, 60_000];
const draftKey = (taskId: string) => `momentum.draft.description.${taskId}`;

function readDraft(taskId: string): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(taskId));
    const d = raw ? (JSON.parse(raw) as Draft) : null;
    if (!d || typeof d.base !== 'string' || Date.now() - d.at > DRAFT_TTL_MS) return null;
    return d;
  } catch {
    return null;
  }
}
function writeDraft(taskId: string, d: Draft) {
  try {
    localStorage.setItem(draftKey(taskId), JSON.stringify(d));
  } catch {
    /* storage full or blocked: the in-memory editor still holds the text */
  }
}
function clearDraft(taskId: string) {
  try {
    localStorage.removeItem(draftKey(taskId));
  } catch {
    /* ignore */
  }
}
/** Drop drafts older than the TTL (called when a pane opens). */
export function pruneDrafts() {
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (!k?.startsWith('momentum.draft.description.')) continue;
      const d = JSON.parse(localStorage.getItem(k) ?? 'null') as Draft | null;
      if (!d || Date.now() - d.at > DRAFT_TTL_MS) localStorage.removeItem(k);
    }
  } catch {
    /* ignore */
  }
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
const isEmptyDoc = (d: JSONContent | null | undefined) =>
  !d ||
  !d.content?.length ||
  (d.content.length === 1 && d.content[0]!.type === 'paragraph' && !d.content[0]!.content);

/**
 * Autosave for a task description. Guarantees (S1.3.1 AC: typed text is never lost):
 * - every change is written to a local draft within ~150 ms (and on page hide / unmount);
 * - saves send the hash of the description they're based on; if someone else changed it the
 *   server answers 409 and we show both versions instead of overwriting either;
 * - offline or signed-out saves keep the draft and retry; the draft resumes on the next open.
 */
export function useDescriptionAutosave(
  task: TaskDetail,
  canEdit: boolean,
  timing: { saveAfterMs?: number; retryMs?: readonly number[] } = {},
) {
  const saveAfter = timing.saveAfterMs ?? SAVE_AFTER_MS;
  const retryDelays = timing.retryMs ?? RETRY_MS;
  const api = useApi();
  const qc = useQueryClient();
  const taskId = task.id;
  const [state, setState] = useState<SaveState>('saved');
  const [conflict, setConflict] = useState<{ theirs: JSONContent | null; theirsHash: string } | null>(null);
  // The document the editor should (re)load; bumps `revision` so the editor knows to replace content.
  const [content, setContent] = useState<{ doc: JSONContent | null; revision: number }>(() => ({
    doc: task.description as JSONContent | null,
    revision: 0,
  }));
  const base = useRef(task.description_hash);
  const current = useRef<JSONContent | null>(task.description as JSONContent | null);
  const saved = useRef<JSONContent | null>(task.description as JSONContent | null);
  const inflight = useRef(false);
  const again = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const draftTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const retry = useRef(0);
  const lastDraft = useRef(0);
  const conflictRef = useRef(conflict);
  conflictRef.current = conflict;

  const dirty = () => current.current !== saved.current;
  const persistDraft = useCallback(() => {
    clearTimeout(draftTimer.current);
    if (dirty()) writeDraft(taskId, { doc: current.current, base: base.current, at: Date.now() });
  }, [taskId]);

  const load = useCallback((doc: JSONContent | null) => {
    current.current = doc;
    setContent((c) => ({ doc, revision: c.revision + 1 }));
  }, []);

  const save = useCallback(async (): Promise<void> => {
    clearTimeout(saveTimer.current);
    if (!canEdit || conflictRef.current) return;
    if (inflight.current) {
      again.current = true;
      return;
    }
    if (!dirty()) return;
    const doc = current.current;
    inflight.current = true;
    setState('saving');
    try {
      const res = (
        await api.PATCH('/api/v1/tasks/{task_id}', {
          params: { path: { task_id: taskId } },
          body: { description: isEmptyDoc(doc) ? null : doc, description_base: base.current },
        })
      ).data!;
      base.current = res.data.description_hash;
      saved.current = doc;
      retry.current = 0;
      syncTask(qc, taskId, {
        description: res.data.description,
        description_hash: res.data.description_hash,
        version: res.data.version,
        updated_at: res.data.updated_at,
      });
      if (current.current === doc) {
        clearDraft(taskId);
        setState('saved');
      } else {
        persistDraft();
        setState('dirty');
        again.current = true;
      }
    } catch (e) {
      persistDraft();
      const err = e instanceof ApiError ? e : null;
      if (err?.code === 'version_conflict') {
        const latest = (
          await api
            .GET('/api/v1/tasks/{task_id}', { params: { path: { task_id: taskId } } })
            .catch(() => null)
        )?.data;
        if (latest && (same(latest.description, doc) || (isEmptyDoc(doc) && !latest.description))) {
          // "Theirs" is exactly our text (e.g. our own earlier save landed late): not a conflict.
          qc.setQueryData(taskKeys.detail(taskId), latest);
          base.current = latest.description_hash;
          saved.current = doc;
          if (current.current === doc) {
            clearDraft(taskId);
            setState('saved');
          } else again.current = true;
        } else {
          if (latest) {
            qc.setQueryData(taskKeys.detail(taskId), latest);
            setConflict({
              theirs: latest.description as JSONContent | null,
              theirsHash: latest.description_hash,
            });
          }
          setState('conflict');
        }
      } else if (err?.status === 401) {
        setState('signed-out');
      } else if (!err || err.status >= 500 || err.status === 0) {
        setState('offline');
        const wait = retryDelays[Math.min(retry.current++, retryDelays.length - 1)];
        saveTimer.current = setTimeout(() => void save(), wait);
      } else {
        setState('error');
        toastError(e, "Couldn't save the description");
      }
    } finally {
      inflight.current = false;
      if (again.current) {
        again.current = false;
        saveTimer.current = setTimeout(() => void save(), 0);
      }
    }
  }, [api, canEdit, persistDraft, qc, taskId, retryDelays]);

  const onChange = useCallback(
    (doc: JSONContent) => {
      // Ignore editor updates that don't change the content (normalization, focus changes).
      if (!dirty() && (same(doc, saved.current) || (isEmptyDoc(doc) && isEmptyDoc(saved.current)))) return;
      current.current = doc;
      if (conflictRef.current) {
        // keep typing safe while a conflict is shown
        persistDraft();
        return;
      }
      setState((s) => (s === 'saving' ? s : 'dirty'));
      // Draft: written on the first keystroke, then at most every DRAFT_AFTER_MS (leading +
      // trailing), so at most a fraction of a second of typing is ever only in memory.
      const now = Date.now();
      if (now - lastDraft.current >= DRAFT_AFTER_MS) {
        lastDraft.current = now;
        persistDraft();
      } else {
        clearTimeout(draftTimer.current);
        draftTimer.current = setTimeout(() => {
          lastDraft.current = Date.now();
          persistDraft();
        }, DRAFT_AFTER_MS);
      }
      clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => void save(), saveAfter);
    },
    [persistDraft, save, saveAfter],
  );

  // On open: resume a draft left from an earlier session (or show it as a conflict).
  useEffect(() => {
    pruneDrafts();
    const draft = readDraft(taskId);
    if (!draft || !canEdit) return;
    if (same(draft.doc, task.description) || (isEmptyDoc(draft.doc) && !task.description)) {
      clearDraft(taskId);
      return;
    }
    if (draft.base === task.description_hash) {
      load(draft.doc);
      setState('dirty');
      saveTimer.current = setTimeout(() => void save(), 0);
    } else {
      load(draft.doc);
      setConflict({ theirs: task.description as JSONContent | null, theirsHash: task.description_hash });
      setState('conflict');
    }
    // run once per task
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // Someone else changed the description while we have no local edits: show theirs.
  useEffect(() => {
    if (task.description_hash === base.current || dirty() || inflight.current || conflictRef.current) return;
    base.current = task.description_hash;
    saved.current = task.description as JSONContent | null;
    load(saved.current);
  }, [task.description_hash, task.description, load]);

  // Retry when the connection comes back; persist the draft when the page is hidden or closed.
  useEffect(() => {
    const online = () => (dirty() ? void save() : undefined);
    const hide = () => persistDraft();
    const vis = () => document.visibilityState === 'hidden' && persistDraft();
    window.addEventListener('online', online);
    window.addEventListener('pagehide', hide);
    document.addEventListener('visibilitychange', vis);
    return () => {
      window.removeEventListener('online', online);
      window.removeEventListener('pagehide', hide);
      document.removeEventListener('visibilitychange', vis);
    };
  }, [persistDraft, save]);

  // Closing the pane or switching task: keep the draft and try one last save. Refs keep this
  // strictly an unmount effect (not re-run when callbacks change identity).
  const saveRef = useRef(save);
  const persistRef = useRef(persistDraft);
  saveRef.current = save;
  persistRef.current = persistDraft;
  useEffect(
    () => () => {
      clearTimeout(draftTimer.current);
      clearTimeout(saveTimer.current);
      if (dirty()) {
        persistRef.current();
        if (!conflictRef.current) void saveRef.current();
      }
    },
    [],
  );

  const keepMine = useCallback(() => {
    if (!conflictRef.current) return;
    base.current = conflictRef.current.theirsHash;
    saved.current = null; // force a save even if identical to what we had
    setConflict(null);
    conflictRef.current = null;
    void save();
  }, [save]);

  const useTheirs = useCallback(() => {
    if (!conflictRef.current) return;
    const { theirs, theirsHash } = conflictRef.current;
    base.current = theirsHash;
    saved.current = theirs;
    clearDraft(taskId);
    setConflict(null);
    conflictRef.current = null;
    load(theirs);
    saved.current = current.current;
    setState('saved');
  }, [load, taskId]);

  return {
    state,
    conflict,
    content,
    onChange,
    flush: save,
    keepMine,
    useTheirs,
    mine: () => current.current,
  };
}
