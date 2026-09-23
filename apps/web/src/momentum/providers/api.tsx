import { createContext, useContext } from 'react';
import type { MomentumClient } from '@/lib/api/client';

export const ApiContext = createContext<MomentumClient | null>(null);

export function useApi(): MomentumClient {
  const api = useContext(ApiContext);
  if (!api) throw new Error('useApi must be used inside <MomentumProvider>');
  return api;
}
