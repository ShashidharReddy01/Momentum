import { MessagesSquare } from 'lucide-react';
import type { RouteObject } from 'react-router';
import { AuthGate, DevLoginPage } from '@/features/auth';
import { HomePage } from '@/features/home';
import { InboxPage, NotificationSettingsPage } from '@/features/notifications';
import { NotFoundPage, Placeholder } from '@/features/placeholders';
import { ProjectPage } from '@/features/projects';
import { MyTasksPage } from '@/features/mytasks';
import { TaskPage } from '@/features/tasks';
import { TagPage } from '@/features/tags';
import { TeamPage } from '@/features/teams';
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
          element: <MyTasksPage />,
          handle: { crumb: 'My Tasks' },
        },
        { path: 'teams/:teamId', element: <TeamPage />, handle: { crumb: 'Team' } },
        { path: 'projects/:projectId/:view?', element: <ProjectPage />, handle: { crumb: 'Project' } },
        { path: 'task/:taskId', element: <TaskPage />, handle: { crumb: 'Task' } },
        { path: 'tags/:tagId', element: <TagPage />, handle: { crumb: 'Tag' } },
        { path: 'inbox', element: <InboxPage />, handle: { crumb: 'Inbox' } },
        {
          path: 'settings/notifications',
          element: <NotificationSettingsPage />,
          handle: { crumb: 'Notification settings' },
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
