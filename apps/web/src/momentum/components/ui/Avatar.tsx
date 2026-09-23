import { useState } from 'react';
import { cn } from '@/lib/cn';

const PALETTE = Array.from({ length: 12 }, (_, i) => `var(--proj-${i + 1})`);

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (
    (parts[0]?.[0] ?? '') + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '')
  ).toUpperCase();
}

/** Initials on a stable color, or the photo when it loads. Plain elements (no Radix): avatars
 * render in every list row, so they need to be cheap to mount. */
export function Avatar({
  name,
  src,
  size = 24,
  isAgent,
  className,
}: {
  name: string;
  src?: string | null;
  size?: number;
  isAgent?: boolean;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const showImage = !!src && !failed;
  return (
    <span
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full',
        isAgent && 'ring-2 ring-amber ring-offset-1 ring-offset-surface',
        className,
      )}
      style={{ width: size, height: size, background: PALETTE[hash(name) % PALETTE.length] }}
      title={name}
      role="img"
      aria-label={name}
    >
      {showImage ? (
        <img src={src} alt="" className="h-full w-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <span aria-hidden className="font-medium text-surface" style={{ fontSize: Math.round(size * 0.42) }}>
          {initials(name)}
        </span>
      )}
    </span>
  );
}
