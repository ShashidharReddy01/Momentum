import type { RouteObject } from 'react-router';
import { AuthGate, DevLoginPage } from '@/features/auth';
import { HomePage } from '@/features/home';
import { InboxPage } from '@/features/notifications';
import { NotFoundPage } from '@/features/placeholders';
import { ProjectPage } from '@/features/projects';
import { MyTasksPage } from '@/features/mytasks';
import { TaskPage } from '@/features/tasks';
import type { RuntimeConfig } from '@/lib/config';
import { Layout } from '@/shell/Layout';

/** Route objects (docs/frontend/frontend-architecture.md §6). Hosts can mount these. The screens
 * people use all day (Home, My Tasks, Inbox, projects, tasks) load with the shell; every other
 * screen is a lazy chunk, which keeps the initial bundle inside its 300 KB gzip budget. A lazy route
 * imports the page's own module, not the feature's index: when the shell also imports that index,
 * a lazy import of it would pull every page it re-exports into the initial chunk. This is the one
 * sanctioned deep import into a feature (frontend-architecture.md §6). */
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
    {
      path: 'f/:token',
      lazy: async () => ({ Component: (await import('@/features/forms/PublicFormPage')).PublicFormPage }),
    },
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
        {
          path: 'teams/:teamId',
          lazy: async () => ({ Component: (await import('@/features/teams/TeamPage')).TeamPage }),
          handle: { crumb: 'Team' },
        },
        { path: 'projects/:projectId/:view?', element: <ProjectPage />, handle: { crumb: 'Project' } },
        {
          path: 'projects/:projectId/forms/:formId',
          lazy: async () => ({ Component: (await import('@/features/forms/FormFillPage')).FormFillPage }),
          handle: { crumb: 'Fill out form' },
        },
        { path: 'task/:taskId', element: <TaskPage />, handle: { crumb: 'Task' } },
        {
          path: 'tags/:tagId',
          lazy: async () => ({ Component: (await import('@/features/tags/TagPage')).TagPage }),
          handle: { crumb: 'Tag' },
        },
        { path: 'inbox', element: <InboxPage />, handle: { crumb: 'Inbox' } },
        {
          path: 'portfolios',
          lazy: async () => ({
            Component: (await import('@/features/portfolios/PortfoliosPage')).PortfoliosPage,
          }),
          handle: { crumb: 'Portfolios' },
        },
        {
          path: 'goals',
          lazy: async () => ({ Component: (await import('@/features/goals/GoalsPage')).GoalsPage }),
          handle: { crumb: 'Goals' },
        },
        {
          path: 'workload',
          lazy: async () => ({ Component: (await import('@/features/workload/WorkloadPage')).WorkloadPage }),
          handle: { crumb: 'Workload' },
        },
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
        {
          path: 'goals/:goalId',
          lazy: async () => ({ Component: (await import('@/features/goals/GoalPage')).GoalPage }),
          handle: { crumb: 'Goal' },
        },
        {
          path: 'portfolios/:portfolioId/:tab?',
          lazy: async () => ({
            Component: (await import('@/features/portfolios/PortfolioPage')).PortfolioPage,
          }),
          handle: { crumb: 'Portfolio' },
        },
        {
          path: 'ai/actions/:actionId',
          lazy: async () => ({ Component: (await import('@/features/ai/AiActionPage')).AiActionPage }),
          handle: { crumb: 'Suggestion' },
        },
        {
          path: 'agents',
          lazy: async () => ({ Component: (await import('@/features/agents/AgentsGallery')).AgentsGallery }),
          handle: { crumb: 'Agents' },
        },
        {
          path: 'agents/new',
          lazy: async () => ({ Component: (await import('@/features/agents/AgentForm')).NewAgentPage }),
          handle: { crumb: 'New agent' },
        },
        {
          path: 'agents/runs/:runId',
          lazy: async () => ({ Component: (await import('@/features/agents/AgentRunPage')).AgentRunPage }),
          handle: { crumb: 'Agent run' },
        },
        {
          path: 'agents/:agentId/edit',
          lazy: async () => ({ Component: (await import('@/features/agents/AgentForm')).EditAgentPage }),
          handle: { crumb: 'Edit agent' },
        },
        {
          path: 'agents/:agentId',
          lazy: async () => ({ Component: (await import('@/features/agents/AgentPage')).AgentPage }),
          handle: { crumb: 'Agent' },
        },
        {
          path: 'search',
          lazy: async () => ({ Component: (await import('@/features/search/SearchPage')).SearchPage }),
          handle: { crumb: 'Search' },
        },
        {
          path: 'settings',
          lazy: async () => ({ Component: (await import('@/features/settings/SettingsPage')).SettingsPage }),
          handle: { crumb: 'Settings' },
        },
        {
          path: 'settings/notifications',
          lazy: async () => ({
            Component: (await import('@/features/notifications/NotificationSettingsPage'))
              .NotificationSettingsPage,
          }),
          handle: { crumb: 'Notification settings' },
        },
        {
          path: 'welcome/asana',
          lazy: async () => ({
            Component: (await import('@/features/onboarding/ComingFromAsanaPage')).ComingFromAsanaPage,
          }),
          handle: { crumb: 'Coming from Asana?' },
        },
        {
          path: 'settings/import/asana',
          lazy: async () => ({
            Component: (await import('@/features/imports/AsanaImportPage')).AsanaImportPage,
          }),
          handle: { crumb: 'Import from Asana' },
        },
        {
          path: 'settings/members',
          lazy: async () => ({ Component: (await import('@/features/members/MembersPage')).MembersPage }),
          handle: { crumb: 'Members' },
        },
        {
          path: 'settings/jobs',
          lazy: async () => ({ Component: (await import('@/features/admin/JobsPage')).JobsPage }),
          handle: { crumb: 'Background jobs' },
        },
        {
          path: 'settings/audit',
          lazy: async () => ({ Component: (await import('@/features/admin/AuditPage')).AuditPage }),
          handle: { crumb: 'Audit trail' },
        },
        {
          path: 'settings/ai',
          lazy: async () => ({ Component: (await import('@/features/ai/AiSettingsPage')).AiSettingsPage }),
          handle: { crumb: 'AI settings' },
        },
        {
          path: 'settings/tokens',
          lazy: async () => ({ Component: (await import('@/features/tokens/TokensPage')).TokensPage }),
          handle: { crumb: 'API tokens' },
        },
        {
          path: 'ask',
          lazy: async () => ({ Component: (await import('@/features/ai/AskPage')).AskPage }),
          handle: { crumb: 'Ask Mo' },
        },
        {
          path: 'ask/:conversationId',
          lazy: async () => ({ Component: (await import('@/features/ai/AskPage')).AskPage }),
          handle: { crumb: 'Ask Mo' },
        },
        ...galleryRoute.map((r) => ({ ...r, path: 'dev/ui', handle: { crumb: 'Component gallery' } })),
        { path: '*', element: <NotFoundPage />, handle: { crumb: 'Not found' } },
      ],
    },
  ];
}
