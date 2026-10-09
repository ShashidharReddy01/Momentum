import { FileX, Minus, Plus } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { EmptyState } from '@/components/common/States';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';
import { whereOnPage, type Prov } from './model';
import { useRecordSource } from './queries';

export interface Highlight {
  path: string;
  label: string;
  prov: Prov;
}

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];

/**
 * The page viewer (spec §12.4): the record's source pages as server-rendered images, zoom, page
 * thumbnails, and a highlight box per located field. Highlights work both ways: the active field's
 * box is outlined and scrolled into view; clicking a box picks its field. Every box is a button
 * named with its field and where it is ("Invoice number: page 1, top right").
 */
export function PageViewer({
  recordId,
  hasSource,
  highlights,
  active,
  onPick,
}: {
  recordId: string;
  hasSource: boolean;
  highlights: Highlight[];
  active: string | null;
  onPick: (path: string) => void;
}) {
  const source = useRecordSource(recordId, hasSource);
  const { api_base } = useMomentumConfig();
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(2);
  const activeBox = useRef<SVGRectElement | null>(null);
  const activeProv = highlights.find((h) => h.path === active)?.prov;

  // picking a field turns to its page (once: the person can still page through by hand)
  const lastActive = useRef(active);
  useEffect(() => {
    if (active === lastActive.current) return;
    lastActive.current = active;
    if (activeProv?.page) setPage(activeProv.page);
  }, [active, activeProv]);
  useEffect(() => {
    activeBox.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  }, [active, page]);

  if (!hasSource)
    return (
      <EmptyState icon={FileX} title="No source document">
        This record wasn’t read from a file, so there’s nothing to show here.
      </EmptyState>
    );
  if (source.isPending) return <Skeleton className="h-[60vh] w-full" />;
  if (source.isError || !source.data.pages.length)
    return (
      <EmptyState icon={FileX} title="Can’t show the document">
        The source file is gone or isn’t a PDF or image.
      </EmptyState>
    );
  const pages = source.data.pages;
  const size = pages[page - 1] ?? pages[0]!;
  const scale = ZOOMS[zoom]!;
  const onPage = highlights.filter((h) => h.prov.page === size.n && h.prov.bbox);
  const pageUrl = (n: number) => `${api_base}/records/${recordId}/pages/${n}`;

  return (
    <section aria-label="Source document" className="flex min-h-0 flex-col gap-2">
      <div className="flex items-center gap-1 text-xs text-muted">
        <span className="mr-auto truncate" title={source.data.filename}>
          {source.data.filename}
          {source.data.locator ? ` · ${source.data.locator}` : ''} · page {size.n} of {pages.length}
        </span>
        <IconButton
          icon={Minus}
          label="Zoom out"
          size="icon-sm"
          disabled={zoom === 0}
          onClick={() => setZoom((z) => Math.max(0, z - 1))}
        />
        <span className="w-10 text-center tabular-nums">{Math.round(scale * 100)}%</span>
        <IconButton
          icon={Plus}
          label="Zoom in"
          size="icon-sm"
          disabled={zoom === ZOOMS.length - 1}
          onClick={() => setZoom((z) => Math.min(ZOOMS.length - 1, z + 1))}
        />
      </div>
      <div className="flex min-h-0 flex-1 gap-2">
        {pages.length > 1 ? (
          <ol aria-label="Pages" className="flex w-16 shrink-0 flex-col gap-1.5 overflow-auto">
            {pages.map((p) => (
              <li key={p.n}>
                <button
                  type="button"
                  aria-label={`Page ${p.n}`}
                  aria-current={p.n === size.n ? 'page' : undefined}
                  onClick={() => setPage(p.n)}
                  className={cn(
                    'block w-full overflow-hidden rounded border bg-surface',
                    p.n === size.n ? 'border-ink' : 'border-hairline hover:border-muted-2',
                  )}
                >
                  <img src={pageUrl(p.n)} alt="" loading="lazy" className="w-full" />
                  <span className="block text-center text-[10px] text-muted">{p.n}</span>
                </button>
              </li>
            ))}
          </ol>
        ) : null}
        <div className="min-w-0 flex-1 overflow-auto rounded-md border border-hairline bg-surface-2 p-2">
          <div className="relative mx-auto" style={{ width: `${scale * 100}%` }}>
            <img
              src={pageUrl(size.n)}
              alt={`Page ${size.n} of ${source.data.filename}`}
              className="block w-full bg-surface shadow-raise"
            />
            <svg
              viewBox={`0 0 ${size.width} ${size.height}`}
              preserveAspectRatio="none"
              className="absolute inset-0 h-full w-full"
              role="group"
              aria-label="Located fields"
            >
              {onPage.map((h) => {
                const [x0, y0, x1, y1] = h.prov.bbox!;
                const isActive = h.path === active;
                return (
                  <rect
                    key={h.path}
                    ref={isActive ? activeBox : undefined}
                    x={x0 - 2}
                    y={y0 - 2}
                    width={x1 - x0 + 4}
                    height={y1 - y0 + 4}
                    rx={2}
                    role="button"
                    tabIndex={0}
                    aria-label={`${h.label}: ${whereOnPage(h.prov, size)}`}
                    aria-pressed={isActive}
                    onClick={() => onPick(h.path)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onPick(h.path);
                      }
                    }}
                    className={cn(
                      'cursor-pointer outline-none',
                      isActive
                        ? 'fill-amber/25 stroke-amber-ink [stroke-width:2]'
                        : 'fill-amber/10 stroke-amber [stroke-width:1] hover:fill-amber/20 focus-visible:stroke-focus',
                    )}
                  >
                    <title>{h.label}</title>
                  </rect>
                );
              })}
            </svg>
          </div>
        </div>
      </div>
    </section>
  );
}
