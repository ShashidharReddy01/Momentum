import { Inbox, ListChecks, MessagesSquare } from 'lucide-react';
import type { RouteObject } from 'react-router';
import { AuthGate, DevLoginPage } from '@/features/auth';
import { HomePage } from '@/features/home';
import { NotFoundPage, Placeholder } from '@/features/placeholders';
import type { RuntimeConfig } from '@/lib/config';
import { Layout } from '@/shell/Layout';

/** Route objects (docs/frontend/frontend-architecture.md §6). Hosts can mount these. */
export function buildRoutes(config: RuntimeConfig): RouteObject[] {
  const devRoutes: RouteObject[] = config.auth.dev_login
    ? [{ path: '/dev/login', element: <DevLoginPage /> }]
    : [];
  const galleryRoute: RouteObject[] =
    config.env !== 'production'
      ? [{ path: '/dev/ui', lazy: async () => ({ Component: (await import('@/features/dev')).UiGallery }) }]
      : [];
  return [
    ...devRoutes,
    {
      element: (
        <AuthGate>
          <Layout />
        </AuthGate>
      ),
      children: [
        { index: true, element: <HomePage />, handle: { crumb: 'Home' } },
        {
          path: 'my-tasks',
          element: <Placeholder icon={ListChecks} title="My Tasks" phase={1} />,
          handle: { crumb: 'My Tasks' },
        },
        {
          path: 'inbox',
          element: <Placeholder icon={Inbox} title="Inbox" phase={2} />,
          handle: { crumb: 'Inbox' },
        },
        {
          path: 'ask',
          element: <Placeholder icon={MessagesSquare} title="Ask Mo" phase={3} />,
          handle: { crumb: 'Ask Mo' },
        },
        ...galleryRoute.map((r) => ({ ...r, path: 'dev/ui', handle: { crumb: 'Component gallery' } })),
        { path: '*', element: <NotFoundPage />, handle: { crumb: 'Not found' } },
      ],
    },
  ];
}
