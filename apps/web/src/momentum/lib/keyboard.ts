import { useEffect, useRef } from 'react';

/** Shortcut spec such as "mod+k", "mod+\\", "?", "g h". `mod` = ⌘ on macOS, Ctrl elsewhere. */
export type Combo = string;

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

export function formatCombo(combo: Combo): string[] {
  return combo.split('+').map((k) => {
    if (k === 'mod') return isMac ? '⌘' : 'Ctrl';
    if (k === 'shift') return '⇧';
    if (k === 'alt') return isMac ? '⌥' : 'Alt';
    return k.length === 1 ? k.toUpperCase() : k;
  });
}

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
}

export function matchesCombo(e: KeyboardEvent, combo: Combo): boolean {
  const parts = combo.toLowerCase().split('+');
  const key = parts[parts.length - 1];
  const wantMod = parts.includes('mod');
  const mod = isMac ? e.metaKey : e.ctrlKey;
  if (wantMod !== mod) return false;
  if (parts.includes('shift') !== e.shiftKey && key !== '?') return false;
  if (parts.includes('alt') !== e.altKey) return false;
  return e.key.toLowerCase() === key;
}

/** Register a global shortcut. Plain-key shortcuts are ignored while typing in a field. */
export function useHotkey(combo: Combo, handler: (e: KeyboardEvent) => void, enabled = true): void {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  });
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (!matchesCombo(e, combo)) return;
      if (!combo.includes('mod') && isTypingTarget(e.target)) return;
      e.preventDefault();
      ref.current(e);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [combo, enabled]);
}

export const SHORTCUTS: { combo: Combo; label: string; phase?: number }[] = [
  { combo: 'mod+k', label: 'Command palette' },
  { combo: 'mod+j', label: 'Toggle Ask Mo' },
  { combo: 'mod+\\', label: 'Collapse sidebar' },
  { combo: '?', label: 'Keyboard shortcuts' },
  { combo: 'q', label: 'Quick add task', phase: 1 },
  { combo: 'mod+enter', label: 'Complete task', phase: 1 },
  { combo: 'mod+z', label: 'Undo last action', phase: 1 },
];
