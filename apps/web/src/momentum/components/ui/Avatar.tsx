import * as A from '@radix-ui/react-avatar';
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
  return (
    <A.Root
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full',
        isAgent && 'ring-2 ring-amber ring-offset-1 ring-offset-paper',
        className,
      )}
      style={{ width: size, height: size, background: PALETTE[hash(name) % PALETTE.length] }}
      title={name}
    >
      {src ? <A.Image src={src} alt={name} className="h-full w-full object-cover" /> : null}
      <A.Fallback className="font-medium text-paper" style={{ fontSize: Math.round(size * 0.42) }}>
        {initials(name)}
      </A.Fallback>
    </A.Root>
  );
}
