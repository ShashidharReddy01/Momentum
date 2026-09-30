import type { RouteObject } from 'react-router';
import { AgentPage, AgentRunPage, AgentsGallery, EditAgentPage, NewAgentPage } from '@/features/agents';
import { AiActionPage, AiSettingsPage, AskPage } from '@/features/ai';
import { AuthGate, DevLoginPage } from '@/features/auth';
import { GoalPage, GoalsPage } from '@/features/goals';
import { FormFillPage, PublicFormPage } from '@/features/forms';
import { HomePage } from '@/features/home';
import { AsanaImportPage } from '@/features/imports';
import { MembersPage } from '@/features/members';
import { InboxPage, NotificationSettingsPage } from '@/features/notifications';
import { NotFoundPage } from '@/features/placeholders';
import { PortfolioPage, PortfoliosPage } from '@/features/portfolios';
import { ProjectPage } from '@/features/projects';
import { MyTasksPage } from '@/features/mytasks';
import { SearchPage } from '@/features/search';
import { TaskPage } from '@/features/tasks';
import { TagPage } from '@/features/tags';
import { TeamPage } from '@/features/teams';
import { TokensPage } from '@/features/tokens';
import { WorkloadPage } from '@/features/workload';
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
    // S4.2.1: the public form link has no session — its own route outside AuthGate/Layout.
    { path: 'f/:token', element: <PublicFormPage /> },
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
        {
          path: 'projects/:projectId/forms/:formId',
          element: <FormFillPage />,
          handle: { crumb: 'Fill out form' },
        },
        { path: 'task/:taskId', element: <TaskPage />, handle: { crumb: 'Task' } },
        { path: 'tags/:tagId', element: <TagPage />, handle: { crumb: 'Tag' } },
        { path: 'inbox', element: <InboxPage />, handle: { crumb: 'Inbox' } },
        { path: 'portfolios', element: <PortfoliosPage />, handle: { crumb: 'Portfolios' } },
        { path: 'goals', element: <GoalsPage />, handle: { crumb: 'Goals' } },
        { path: 'workload', element: <WorkloadPage />, handle: { crumb: 'Workload' } },
        {
          path: 'dashboards',
          lazy: async () => ({ Component: (await import('@/features/dashboards')).DashboardsPage }),
          handle: { crumb: 'Dashboards' },
        },
        {
          path: 'dashboards/:dashboardId',
          lazy: async () => ({ Component: (await import('@/features/dashboards')).DashboardPage }),
          handle: { crumb: 'Dashboard' },
        },
        { path: 'goals/:goalId', element: <GoalPage />, handle: { crumb: 'Goal' } },
        { path: 'portfolios/:portfolioId', element: <PortfolioPage />, handle: { crumb: 'Portfolio' } },
        { path: 'ai/actions/:actionId', element: <AiActionPage />, handle: { crumb: 'Suggestion' } },
        { path: 'agents', element: <AgentsGallery />, handle: { crumb: 'Agents' } },
        { path: 'agents/new', element: <NewAgentPage />, handle: { crumb: 'New agent' } },
        { path: 'agents/runs/:runId', element: <AgentRunPage />, handle: { crumb: 'Agent run' } },
        { path: 'agents/:agentId/edit', element: <EditAgentPage />, handle: { crumb: 'Edit agent' } },
        { path: 'agents/:agentId', element: <AgentPage />, handle: { crumb: 'Agent' } },
        { path: 'search', element: <SearchPage />, handle: { crumb: 'Search' } },
        {
          path: 'settings/notifications',
          element: <NotificationSettingsPage />,
          handle: { crumb: 'Notification settings' },
        },
        {
          path: 'settings/import/asana',
          element: <AsanaImportPage />,
          handle: { crumb: 'Import from Asana' },
        },
        {
          path: 'settings/members',
          element: <MembersPage />,
          handle: { crumb: 'Members' },
        },
        { path: 'settings/ai', element: <AiSettingsPage />, handle: { crumb: 'AI settings' } },
        { path: 'settings/tokens', element: <TokensPage />, handle: { crumb: 'API tokens' } },
        { path: 'ask', element: <AskPage />, handle: { crumb: 'Ask Mo' } },
        { path: 'ask/:conversationId', element: <AskPage />, handle: { crumb: 'Ask Mo' } },
        ...galleryRoute.map((r) => ({ ...r, path: 'dev/ui', handle: { crumb: 'Component gallery' } })),
        { path: '*', element: <NotFoundPage />, handle: { crumb: 'Not found' } },
      ],
    },
  ];
}
