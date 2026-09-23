import { createContext, useContext } from 'react';

/** Radix portals render into the Momentum root so design tokens apply to menus and dialogs. */
export const PortalContext = createContext<HTMLElement | null>(null);

export function usePortalContainer(): HTMLElement | undefined {
  return useContext(PortalContext) ?? undefined;
}
