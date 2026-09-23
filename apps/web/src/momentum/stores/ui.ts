import { createContext, useContext } from 'react';
import { createStore, useStore, type StoreApi } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type Theme = 'light' | 'dark';
export const PALETTES = ['petrol', 'aubergine', 'indigo', 'forest', 'graphite'] as const;
export type Palette = (typeof PALETTES)[number];

export interface UiState {
  theme: Theme;
  palette: Palette;
  sidebarCollapsed: boolean;
  askMoOpen: boolean;
  paletteOpen: boolean;
  shortcutsOpen: boolean;
  setTheme: (t: Theme) => void;
  setPalette: (p: Palette) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  setAskMoOpen: (open: boolean) => void;
  setPaletteOpen: (open: boolean) => void;
  setShortcutsOpen: (open: boolean) => void;
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
        palette: 'petrol',
        sidebarCollapsed: false,
        askMoOpen: false,
        paletteOpen: false,
        shortcutsOpen: false,
        setTheme: (theme) => set({ theme }),
        setPalette: (palette) => set({ palette }),
        toggleTheme: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
        toggleSidebar: () => set({ sidebarCollapsed: !get().sidebarCollapsed }),
        setAskMoOpen: (askMoOpen) => set({ askMoOpen }),
        setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
        setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
      }),
      {
        name: storageKey,
        storage: createJSONStorage(safeLocalStorage),
        partialize: (s) => ({ theme: s.theme, palette: s.palette, sidebarCollapsed: s.sidebarCollapsed }),
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
