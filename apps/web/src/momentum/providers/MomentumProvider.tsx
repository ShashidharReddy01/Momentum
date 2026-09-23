import '../styles/index.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Toaster } from 'sonner';
import { TooltipProvider } from '@/components/ui/Tooltip';
import { createApiClient, type MomentumClient } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import { ConfigContext, loadRuntimeConfig, type RuntimeConfig } from '@/lib/config';
import { UndoStack, UndoStackContext } from '@/lib/undo';
import { createUiStore, UiStoreContext, useUi } from '@/stores/ui';
import { ApiContext } from './api';
import { PortalContext } from './portal';

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      },
    },
  });
}

export interface MomentumProviderProps {
  basePath?: string;
  /** Pre-loaded config (tests, SSR, or a host that already fetched it). */
  config?: RuntimeConfig;
  children: ReactNode;
}

/** Everything a mounted Momentum app needs. Each mount gets its own clients and stores. */
export function MomentumProvider({ basePath = '', config: preset, children }: MomentumProviderProps) {
  const [config, setConfig] = useState<RuntimeConfig | null>(preset ?? null);
  const [error, setError] = useState<string | null>(null);
  const [queryClient] = useState(makeQueryClient);
  const [uiStore] = useState(() => createUiStore(`momentum.ui${basePath || ''}`));
  const [api] = useState<MomentumClient>(() => createApiClient(basePath));
  const [undoStack] = useState(() => new UndoStack());

  useEffect(() => {
    if (preset) return;
    loadRuntimeConfig(basePath)
      .then(setConfig)
      .catch((e: unknown) => setError(String(e)));
  }, [basePath, preset]);

  return (
    <UiStoreContext.Provider value={uiStore}>
      <Root>
        {error ? (
          <p role="alert" className="p-8 text-sm text-crit">
            Momentum could not start: {error}
          </p>
        ) : !config ? (
          <div className="p-8 text-sm text-muted" aria-busy>
            Loading Momentum…
          </div>
        ) : (
          <ConfigContext.Provider value={config}>
            <ApiContext.Provider value={api}>
              <QueryClientProvider client={queryClient}>
                <UndoStackContext.Provider value={undoStack}>
                  <TooltipProvider>{children}</TooltipProvider>
                </UndoStackContext.Provider>
              </QueryClientProvider>
            </ApiContext.Provider>
          </ConfigContext.Provider>
        )}
      </Root>
    </UiStoreContext.Provider>
  );
}

function Root({ children }: { children: ReactNode }) {
  const theme = useUi((s) => s.theme);
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  return (
    <div ref={setEl} className="momentum-root" data-momentum data-theme={theme}>
      <PortalContext.Provider value={el}>
        {children}
        <Toaster position="bottom-center" theme={theme} toastOptions={{ className: 'momentum-toast' }} />
      </PortalContext.Provider>
    </div>
  );
}
