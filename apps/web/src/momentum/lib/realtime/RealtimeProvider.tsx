import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { UNAUTHENTICATED_EVENT } from '@/lib/api/client';
import { useMomentumConfig } from '@/lib/config';
import { RealtimeClient, realtimeUrl } from './client';
import type { ConnectionState, RealtimeEvent } from './types';

const RealtimeContext = createContext<RealtimeClient | null>(null);
const ConnectionStateContext = createContext<ConnectionState>('closed');

/**
 * One websocket connection per mounted app, shared by every `useChannel` call. Mounted inside
 * `AuthGate` (features/auth/AuthGate.tsx) — only once the user is known — so it connects with
 * an already-valid session cookie and tears down cleanly on sign-out.
 *
 * A host whose proxy doesn't forward websocket upgrades, or that sets `features.realtime:
 * false` (`MOMENTUM_REALTIME_ENABLED=false`), simply never connects: every `useChannel` call
 * becomes a no-op and the app behaves exactly as Phase 1 did (refetch on window focus).
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const config = useMomentumConfig();
  const [client] = useState<RealtimeClient | null>(() =>
    config.features.realtime
      ? new RealtimeClient(realtimeUrl(config.base_path), () =>
          window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT)),
        )
      : null,
  );
  const [state, setState] = useState<ConnectionState>('closed');

  useEffect(() => {
    if (!client) return;
    const off = client.onStateChange(setState);
    client.connect();
    return () => {
      off();
      client.close();
    };
  }, [client]);

  return (
    <RealtimeContext.Provider value={client}>
      <ConnectionStateContext.Provider value={state}>{children}</ConnectionStateContext.Provider>
    </RealtimeContext.Provider>
  );
}

export function useRealtimeState(): ConnectionState {
  return useContext(ConnectionStateContext);
}

/**
 * Subscribes to a channel while mounted (and while `channel` is non-null); shares one wire
 * subscription with every other `useChannel` call on the same channel. `onEvent` may change
 * freely across renders without re-subscribing.
 */
export function useChannel(channel: string | null, onEvent: (event: RealtimeEvent) => void): void {
  const client = useContext(RealtimeContext);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!client || !channel) return;
    return client.subscribe(channel, (event) => handlerRef.current(event));
  }, [client, channel]);
}
