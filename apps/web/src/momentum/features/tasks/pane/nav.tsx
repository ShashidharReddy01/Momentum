import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';

/**
 * Which task the pane shows (`?task=<id>` in the URL) and the order of the list beside it, so the
 * pane can step through tasks with J/K and the list can follow along.
 */
export interface TaskNav {
  openId: string | null;
  open: (id: string, opts?: { replace?: boolean }) => void;
  close: () => void;
  setOrder: (ids: readonly string[]) => void;
  step: (dir: 1 | -1) => void;
}

const Ctx = createContext<TaskNav | null>(null);

export function TaskNavProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const openId = params.get('task');
  const order = useRef<readonly string[]>([]);
  const open = useCallback(
    (id: string, opts?: { replace?: boolean }) =>
      setParams(
        (p) => {
          const n = new URLSearchParams(p);
          n.set('task', id);
          return n;
        },
        { replace: opts?.replace ?? false },
      ),
    [setParams],
  );
  const close = useCallback(
    () =>
      setParams((p) => {
        const n = new URLSearchParams(p);
        n.delete('task');
        return n;
      }),
    [setParams],
  );
  const setOrder = useCallback((ids: readonly string[]) => {
    order.current = ids;
  }, []);
  const step = useCallback(
    (dir: 1 | -1) => {
      const ids = order.current;
      if (!openId || !ids.length) return;
      const i = ids.indexOf(openId);
      const next = ids[i < 0 ? 0 : Math.min(ids.length - 1, Math.max(0, i + dir))];
      if (next && next !== openId) open(next, { replace: true });
    },
    [open, openId],
  );
  const value = useMemo(
    () => ({ openId, open, close, setOrder, step }),
    [openId, open, close, setOrder, step],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The pane navigation, or null outside a page that hosts a pane. */
export const useTaskNav = () => useContext(Ctx);
