import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect } from 'react';
import { toast } from 'sonner';
import type { MomentumClient } from '@/lib/api/client';
import { useApi } from '@/providers/api';
import { isTypingTarget } from './keyboard';
import { markMine } from './realtime/mine';
import { toastError } from './toast';

export interface UndoMeta {
  activity_id?: string | null;
  batch_id?: string | null;
}

interface UndoEntry {
  key: string; // activity or batch id
  body: { activity_id: string } | { batch_id: string };
  label: string;
  at: number;
  onUndone?: () => void;
}

const MAX_ENTRIES = 50;
const UNDO_WINDOW_MS = 24 * 3600_000; // the server's limit

/** This session's undoable actions, newest last (⌘Z pops). One per mounted app. */
export class UndoStack {
  private entries: UndoEntry[] = [];
  push(label: string, meta: UndoMeta | undefined, onUndone?: () => void): UndoEntry | null {
    const body: UndoEntry['body'] | null = meta?.batch_id
      ? { batch_id: meta.batch_id }
      : meta?.activity_id
        ? { activity_id: meta.activity_id }
        : null;
    if (!body) return null;
    const entry: UndoEntry = {
      key: 'batch_id' in body ? body.batch_id : (body as { activity_id: string }).activity_id,
      body,
      label,
      at: Date.now(),
      onUndone,
    };
    this.entries = [...this.entries.filter((e) => e.key !== entry.key), entry].slice(-MAX_ENTRIES);
    // this mutation's own realtime echo shouldn't trigger a redundant refetch — its onSuccess
    // (which is what called us) already applied the change
    markMine(meta?.activity_id);
    return entry;
  }
  remove(key: string) {
    this.entries = this.entries.filter((e) => e.key !== key);
  }
  pop(): UndoEntry | undefined {
    const now = Date.now();
    this.entries = this.entries.filter((e) => now - e.at < UNDO_WINDOW_MS);
    return this.entries.pop();
  }
  get size() {
    return this.entries.length;
  }
}

export const UndoStackContext = createContext<UndoStack | null>(null);
const fallbackStack = new UndoStack();
const useUndoStack = () => useContext(UndoStackContext) ?? fallbackStack;

async function runUndo(api: MomentumClient, qc: QueryClient, entry: UndoEntry): Promise<boolean> {
  try {
    await api.POST('/api/v1/undo', { body: entry.body });
    await qc.invalidateQueries();
    entry.onUndone?.();
    return true;
  } catch (e) {
    toastError(e, "Couldn't undo");
    return false;
  }
}

/**
 * Returns `notify(message, meta)`: a toast with an Undo action for a completed mutation. The
 * action is also put on the session undo stack (⌘Z).
 */
export function useUndoToast() {
  const api = useApi();
  const qc = useQueryClient();
  const stack = useUndoStack();
  return useCallback(
    (message: string, meta: UndoMeta | undefined, onUndone?: () => void) => {
      const entry = stack.push(message, meta, onUndone);
      if (!entry) {
        toast.success(message);
        return;
      }
      toast.success(message, {
        duration: 6000,
        action: {
          label: 'Undo',
          onClick: async () => {
            stack.remove(entry.key);
            if (await runUndo(api, qc, entry)) toast('Undone');
          },
        },
      });
    },
    [api, qc, stack],
  );
}

/** Record an undoable action without a toast (renames, quick creates, single drags). */
export function useRecordUndo() {
  const stack = useUndoStack();
  return useCallback(
    (label: string, meta: UndoMeta | undefined, onUndone?: () => void) =>
      void stack.push(label, meta, onUndone),
    [stack],
  );
}

/** ⌘Z / Ctrl+Z outside text fields: undo the last action of this session (text fields keep their
 * own undo). */
export function useUndoShortcut() {
  const api = useApi();
  const qc = useQueryClient();
  const stack = useUndoStack();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey || e.key.toLowerCase() !== 'z') return;
      if (isTypingTarget(e.target)) return;
      e.preventDefault();
      const entry = stack.pop();
      if (!entry) {
        toast('Nothing to undo');
        return;
      }
      void runUndo(api, qc, entry).then((ok) => ok && toast(`Undone: ${entry.label}`));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [api, qc, stack]);
}
