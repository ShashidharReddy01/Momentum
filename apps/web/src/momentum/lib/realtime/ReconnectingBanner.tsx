import { useRealtimeState } from './RealtimeProvider';

/** Shown only once a connection has actually been lost mid-session — never on first load
 * (state starts 'connecting', not 'reconnecting') and never when realtime is simply off. */
export function ReconnectingBanner() {
  const state = useRealtimeState();
  if (state !== 'reconnecting') return null;
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 bg-warn-tint px-3 py-1.5 text-xs text-ink-2"
    >
      <span className="size-1.5 animate-pulse rounded-full bg-warn" aria-hidden />
      Reconnecting…
    </div>
  );
}
