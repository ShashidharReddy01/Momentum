import { useVirtualizer } from '@tanstack/react-virtual';
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

/** Sections with more rows than this render only what's on screen (plus overscan). Smaller ones
 * render fully, which keeps browser find (⌘F) and simple DOM for everyday projects. */
export const VIRTUALIZE_OVER = 150;
export const ROW_HEIGHT = 36; // TaskRow is h-9 incl. its bottom border

function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let node = el?.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === 'auto' || overflowY === 'scroll') return node;
  }
  return document.scrollingElement as HTMLElement | null;
}

/**
 * Renders `items` in order; above {@link VIRTUALIZE_OVER} items only the visible window is mounted.
 * Rows have a fixed height, so offsets are exact without measuring.
 */
export function VirtualRows<T>({
  items,
  getKey,
  render,
}: {
  items: readonly T[];
  getKey: (item: T) => string;
  render: (item: T) => ReactNode;
}) {
  if (items.length <= VIRTUALIZE_OVER)
    return (
      <>
        {items.map((item) => (
          <div key={getKey(item)}>{render(item)}</div>
        ))}
      </>
    );
  return <Windowed items={items} getKey={getKey} render={render} />;
}

function Windowed<T>({
  items,
  getKey,
  render,
}: {
  items: readonly T[];
  getKey: (item: T) => string;
  render: (item: T) => ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [scroller, setScroller] = useState<HTMLElement | null>(null);
  const [margin, setMargin] = useState(0);

  useLayoutEffect(() => setScroller(scrollParent(ref.current)), []);
  // Offset of this list inside the scroll content. Content above it can change size (sections
  // collapsing, rows added); that resizes the scroller's content, which the observer reports.
  // (Not re-read on every render: that forced a layout per scroll frame.)
  const read = useRef<() => void>(() => undefined);
  read.current = () => {
    const el = ref.current;
    if (!el || !scroller) return;
    const m = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    setMargin((prev) => (Math.abs(prev - m) > 0.5 ? m : prev));
  };
  useLayoutEffect(() => {
    if (!scroller) return;
    read.current();
    const ro = new ResizeObserver(() => read.current());
    ro.observe(scroller);
    for (const child of scroller.children) ro.observe(child);
    return () => ro.disconnect();
  }, [scroller]);

  const v = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    scrollMargin: margin,
    // Batch scroll updates with React's normal scheduling instead of a synchronous render per
    // scroll event (5 sections = 5 flushSync renders per event before this). Fixed-height rows
    // plus overscan keep the edges filled.
    useFlushSync: false,
    getItemKey: (i) => getKey(items[i]!),
  });

  return (
    <div ref={ref} style={{ height: v.getTotalSize(), position: 'relative', contain: 'layout style' }}>
      {v.getVirtualItems().map((row) => (
        <div
          key={row.key}
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: ROW_HEIGHT,
            contain: 'layout style',
            transform: `translateY(${row.start - margin}px)`,
          }}
        >
          {render(items[row.index]!)}
        </div>
      ))}
    </div>
  );
}
