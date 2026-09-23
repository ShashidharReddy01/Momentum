import { createContext, useContext } from 'react';

/** Runtime configuration served by GET {basePath}/api/v1/config. */
export interface RuntimeConfig {
  version: string;
  env: 'local' | 'test' | 'production';
  base_path: string;
  api_base: string;
  ai_enabled: boolean;
  auth: { mode: string; login_url: string; dev_login: boolean };
  features: Record<string, boolean>;
}

export const ConfigContext = createContext<RuntimeConfig | null>(null);

export function useMomentumConfig(): RuntimeConfig {
  const cfg = useContext(ConfigContext);
  if (!cfg) throw new Error('useMomentumConfig must be used inside <MomentumProvider>');
  return cfg;
}

export async function loadRuntimeConfig(
  basePath: string,
  fetchImpl: typeof fetch = fetch,
): Promise<RuntimeConfig> {
  const res = await fetchImpl(`${basePath}/api/v1/config`, { credentials: 'include' });
  if (!res.ok) throw new Error(`config -> ${res.status}`);
  return (await res.json()) as RuntimeConfig;
}
