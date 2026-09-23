/**
 * "Did I just do this?" — a short-lived, module-level set of activity ids this tab produced,
 * so the realtime echo of the actor's own mutation can be recognized and skipped (the
 * mutation's own onSuccess already reconciled the cache from the server's response; reacting
 * to the echo too would just be a redundant, visibly-flickery refetch).
 *
 * `lib/undo.ts` calls `markMine` for every mutation that reports an activity_id (which is
 * effectively all of them — see UndoMeta), so this works for free across the whole app rather
 * than needing every mutation site to opt in individually.
 *
 * Known gap: bulk operations (POST /tasks/bulk, multi-task move) don't currently expose the
 * per-row activity ids to the frontend, only a shared batch_id — so a bulk action's own realtime
 * echoes aren't suppressed yet. Harmless (an extra background refetch, already-correct data),
 * just not silent. Tracked in STATUS.md.
 */

const TTL_MS = 30_000;
const mine = new Map<string, number>();

export function markMine(activityId: string | null | undefined): void {
  if (!activityId) return;
  prune();
  mine.set(activityId, Date.now() + TTL_MS);
}

export function isMine(activityId: string | null | undefined): boolean {
  if (!activityId) return false;
  const expires = mine.get(activityId);
  if (expires === undefined) return false;
  if (expires < Date.now()) {
    mine.delete(activityId);
    return false;
  }
  // consumed: the point is to skip exactly the one echo we were waiting for
  mine.delete(activityId);
  return true;
}

function prune(): void {
  if (mine.size < 200) return;
  const now = Date.now();
  for (const [id, expires] of mine) if (expires < now) mine.delete(id);
}
