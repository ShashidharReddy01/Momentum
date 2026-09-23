import { useMemo } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router';
import { useMomentumConfig } from '@/lib/config';
import { MomentumProvider } from '@/providers/MomentumProvider';
import { buildRoutes } from './routes';

export interface MomentumAppProps {
  /** Mount prefix, e.g. "/momentum" when embedded in a host app. */
  basePath?: string;
}

export function MomentumApp({ basePath = '' }: MomentumAppProps) {
  return (
    <MomentumProvider basePath={basePath}>
      <MomentumRouter basePath={basePath} />
    </MomentumProvider>
  );
}

function MomentumRouter({ basePath }: { basePath: string }) {
  const config = useMomentumConfig();
  const router = useMemo(
    () => createBrowserRouter(buildRoutes(config), { basename: basePath || '/' }),
    [config, basePath],
  );
  return <RouterProvider router={router} />;
}
