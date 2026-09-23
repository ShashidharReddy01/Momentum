import type { RuntimeConfig } from '@/lib/config';

/** Synthetic fixtures for tests and component development (never real data). */
export function configFixture(overrides: Partial<RuntimeConfig> = {}): RuntimeConfig {
  const base = overrides.base_path ?? '';
  return {
    version: '0.1.0',
    env: 'test',
    base_path: base,
    api_base: `${base}/api/v1`,
    ai_enabled: true,
    auth: { mode: 'dev', login_url: `${base}/dev/login?return_to=/`, dev_login: true },
    features: { realtime: true },
    ...overrides,
  };
}

export const ravi = {
  id: '01a0ccaf-8f68-77d2-a888-584ea1e80ea8',
  email: 'ravi@acme-demo.test',
  name: 'Ravi Kumar',
  avatar_url: null,
  role: 'member',
  status: 'active',
  is_agent: false,
  timezone: 'Asia/Kolkata',
};

export const workspace = { id: '01a0ccaf-0000-7000-8000-000000000001', name: 'Acme Demo', slug: 'default' };
