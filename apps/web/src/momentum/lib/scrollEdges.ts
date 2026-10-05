import { useCallback, useEffect, useState } from 'react';

/** Whether a horizontally scrolling element has more content to its left or right, for edge
 * fades that tell people a row of columns or tabs continues. Attach `ref` to the scroller and
 * call `update` from its `onScroll`; it also updates on resize. A callback ref, so it works for
 * elements that mount after the component does (e.g. once data has loaded). */
export function useScrollEdges() {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const update = useCallback(() => {
    if (!el) return;
    const left = el.scrollLeft > 1;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((e) => (e.left === left && e.right === right ? e : { left, right }));
  }, [el]);
  useEffect(() => {
    update();
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    for (const child of Array.from(el.children)) ro.observe(child);
    return () => ro.disconnect();
  }, [el, update]);
  return { ...edges, update, ref: setEl as (node: HTMLElement | null) => void };
}
