/**
 * List selection model (pure; unit-tested). `order` is the visible task ids in display order.
 *
 * - click: focus the row, clear the selection, set the range anchor
 * - ⌘/Ctrl+click: toggle the row (the anchor row joins when starting a selection)
 * - Shift+click / Shift+↑↓: select the range anchor → row
 * - ⌘A: select every visible row of the focused row's section
 */
export interface Selection {
  selected: ReadonlySet<string>;
  anchor: string | null;
  focus: string | null;
}

export const emptySelection: Selection = { selected: new Set(), anchor: null, focus: null };

export interface Modifiers {
  shift?: boolean;
  meta?: boolean;
}

function range(order: readonly string[], a: string, b: string): string[] {
  const i = order.indexOf(a);
  const j = order.indexOf(b);
  if (i < 0 || j < 0) return [b];
  return order.slice(Math.min(i, j), Math.max(i, j) + 1);
}

export function clickRow(s: Selection, id: string, mods: Modifiers, order: readonly string[]): Selection {
  if (mods.shift) {
    const anchor = s.anchor && order.includes(s.anchor) ? s.anchor : null;
    if (anchor) return { ...s, selected: new Set(range(order, anchor, id)), anchor, focus: id };
  }
  if (mods.meta) {
    const next = new Set(s.selected);
    if (next.size === 0 && s.anchor && s.anchor !== id && order.includes(s.anchor)) next.add(s.anchor);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return { selected: next, anchor: id, focus: id };
  }
  return { selected: new Set(), anchor: id, focus: id };
}

/** ↑/↓ (plain: move focus and clear selection; shift: extend the range from the anchor). */
export function step(s: Selection, dir: 1 | -1, extend: boolean, order: readonly string[]): Selection {
  if (order.length === 0) return s;
  const at = s.focus ? order.indexOf(s.focus) : -1;
  const nextIndex =
    at < 0 ? (dir === 1 ? 0 : order.length - 1) : Math.min(order.length - 1, Math.max(0, at + dir));
  const focus = order[nextIndex]!;
  if (extend) {
    // extend from the current anchor while a range exists; otherwise start at the focused row
    const anchor =
      s.selected.size > 0 && s.anchor && order.includes(s.anchor) ? s.anchor : (s.focus ?? focus);
    return { selected: new Set(range(order, anchor, focus)), anchor, focus };
  }
  return { selected: new Set(), anchor: focus, focus };
}

export function selectAll(s: Selection, ids: readonly string[]): Selection {
  return { ...s, selected: new Set(ids), anchor: ids[0] ?? s.anchor, focus: s.focus ?? ids[0] ?? null };
}

/** Drop ids that are no longer visible (deleted, completed and hidden, filtered out). */
export function prune(s: Selection, order: readonly string[]): Selection {
  const visible = new Set(order);
  const kept = [...s.selected].filter((id) => visible.has(id));
  const focus = s.focus && visible.has(s.focus) ? s.focus : null;
  const anchor = s.anchor && visible.has(s.anchor) ? s.anchor : null;
  if (kept.length === s.selected.size && focus === s.focus && anchor === s.anchor) return s;
  return { selected: new Set(kept), anchor, focus };
}

/** The tasks an action applies to: the selection, or the focused row alone. In display order. */
export function targets(s: Selection, order: readonly string[]): string[] {
  if (s.selected.size > 0) return order.filter((id) => s.selected.has(id));
  return s.focus && order.includes(s.focus) ? [s.focus] : [];
}

export type DropPlacement = 'before' | 'after';

/**
 * Turn a drop (anchor row + before/after, or a section end) into server neighbors for moving
 * `moving` tasks. `sectionOrder` is the target section's rows in display order. Returns null when
 * the drop would not change anything.
 */
export function dropNeighbors(
  sectionOrder: readonly string[],
  moving: readonly string[],
  anchorId: string | null,
  placement: DropPlacement,
): { afterId: string | null; beforeId: string | null } | null {
  const movingSet = new Set(moving);
  const rest = sectionOrder.filter((id) => !movingSet.has(id));
  let index: number;
  if (anchorId === null) {
    index = rest.length;
  } else if (!movingSet.has(anchorId)) {
    index = rest.indexOf(anchorId) + (placement === 'after' ? 1 : 0);
  } else {
    // dropped on one of the dragged rows: keep the block where that row's neighbors are
    const i = sectionOrder.indexOf(anchorId);
    const before = sectionOrder.slice(0, i).filter((id) => !movingSet.has(id));
    index = before.length;
  }
  const afterId = rest[index - 1] ?? null;
  const beforeId = rest[index] ?? null;
  // no-op if the moving block already sits exactly there, contiguous and in order
  const current = sectionOrder.filter((id) => movingSet.has(id));
  if (current.length === moving.length) {
    const first = sectionOrder.indexOf(current[0]!);
    const contiguous = current.every((id, k) => sectionOrder[first + k] === id);
    if (
      contiguous &&
      sectionOrder[first - 1] === (afterId ?? undefined) &&
      (sectionOrder[first + current.length] ?? null) === beforeId
    )
      return null;
  }
  return afterId ? { afterId, beforeId: null } : { afterId: null, beforeId };
}
