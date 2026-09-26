import { createContext, useContext } from 'react';
import { createStore, useStore, type StoreApi } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type Theme = 'light' | 'dark';
export interface MoRequest {
  id: number;
  text: string;
  kind: 'command' | 'chat';
}

export interface UiState {
  theme: Theme;
  sidebarCollapsed: boolean;
  /** Sidebar drawer on narrow screens (not persisted). */
  drawerOpen: boolean;
  /** Quick add task dialog (Create → Task, `Q`). */
  quickAddOpen: boolean;
  setQuickAddOpen: (open: boolean) => void;
  setDrawerOpen: (open: boolean) => void;
  askMoOpen: boolean;
  paletteOpen: boolean;
  shortcutsOpen: boolean;
  /** Breadcrumb override set by pages that know entity names (cleared on unmount). */
  crumbs: string[] | null;
  setCrumbs: (c: string[] | null) => void;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  setAskMoOpen: (open: boolean) => void;
  setPaletteOpen: (open: boolean) => void;
  setShortcutsOpen: (open: boolean) => void;
  /** Text the palette opens with (Edit on a Mo suggestion puts the request back, S3.2.2). */
  paletteQuery: string;
  openPalette: (query?: string) => void;
  /** A request for Mo from elsewhere, taken by the Ask Mo panel: a ⌘K command ("Ask Mo to do
   * this", S3.2.2) or a chat question ("Ask Mo about this", S3.3.2). */
  moRequest: MoRequest | null;
  sendToMo: (text: string, kind?: MoRequest['kind']) => void;
  takeMoRequest: () => MoRequest | null;
}

function safeLocalStorage(): Storage {
  try {
    return window.localStorage;
  } catch {
    const mem = new Map<string, string>();
    return {
      getItem: (k) => mem.get(k) ?? null,
      setItem: (k, v) => void mem.set(k, v),
      removeItem: (k) => void mem.delete(k),
      clear: () => mem.clear(),
      key: () => null,
      length: 0,
    };
  }
}

function prefersDark(): boolean {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return false;
  }
}

/** One store per mounted Momentum app (no module-level singletons; ADR-0006). */
export function createUiStore(storageKey = 'momentum.ui'): StoreApi<UiState> {
  return createStore<UiState>()(
    persist(
      (set, get) => ({
        theme: prefersDark() ? 'dark' : 'light',
        sidebarCollapsed: false,
        drawerOpen: false,
        quickAddOpen: false,
        setQuickAddOpen: (quickAddOpen) => set({ quickAddOpen }),
        setDrawerOpen: (drawerOpen) => set({ drawerOpen }),
        askMoOpen: false,
        paletteOpen: false,
        shortcutsOpen: false,
        crumbs: null,
        setCrumbs: (crumbs) => set({ crumbs }),
        setTheme: (theme) => set({ theme }),
        toggleTheme: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
        toggleSidebar: () => set({ sidebarCollapsed: !get().sidebarCollapsed }),
        setAskMoOpen: (askMoOpen) => set({ askMoOpen }),
        setPaletteOpen: (paletteOpen) =>
          set(paletteOpen ? { paletteOpen } : { paletteOpen, paletteQuery: '' }),
        setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
        paletteQuery: '',
        openPalette: (paletteQuery = '') => set({ paletteOpen: true, paletteQuery }),
        moRequest: null,
        sendToMo: (text, kind = 'command') =>
          set({ askMoOpen: true, moRequest: { id: Date.now() + Math.random(), text, kind } }),
        takeMoRequest: () => {
          const req = get().moRequest;
          if (req) set({ moRequest: null });
          return req;
        },
      }),
      {
        name: storageKey,
        storage: createJSONStorage(safeLocalStorage),
        partialize: (s) => ({ theme: s.theme, sidebarCollapsed: s.sidebarCollapsed }),
      },
    ),
  );
}

export const UiStoreContext = createContext<StoreApi<UiState> | null>(null);

export function useUi<T>(selector: (s: UiState) => T): T {
  const store = useContext(UiStoreContext);
  if (!store) throw new Error('useUi must be used inside <MomentumProvider>');
  return useStore(store, selector);
}
