import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { attachmentHandlers } from '@/mocks/attachments';
import { authHandlers } from '@/mocks/handlers';
import { multiHomingHandlers } from '@/mocks/multiHoming';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

const SEEDED = {
  id: 'att-1',
  task_id: 'task-1',
  comment_id: null,
  filename: 'notes.txt',
  mime: 'text/plain',
  size_bytes: 11,
  sha256: 'x'.repeat(64),
  extract_status: 'pending',
  uploaded_by: 'user-ravi',
  created_at: new Date().toISOString(),
};

// The upload-via-file-picker interaction itself isn't exercised end-to-end here: jsdom's
// File/FormData objects aren't recognized by MSW's undici-backed request interceptor, so a
// real multipart POST hangs indefinitely in this test environment (a known jsdom+MSW+File
// friction point, not specific to this feature). List/download-link/delete — the rest of the
// component — are covered against seeded data instead; the upload path was verified manually.
describe('Task attachments (S2.6.1)', () => {
  it('lists a seeded file with a download link, and removes it', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
      ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
      ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
      ...multiHomingHandlers(
        '',
        [{ id: 'seed-1', name: 'Website Revamp', color: null }],
        [{ task_id: 'task-1', project_id: 'seed-1', section_id: 'sec-1', position: '100000' }],
      ),
      ...attachmentHandlers('', [SEEDED]),
    );
    window.history.replaceState(null, '', '/projects/seed-1');
    render(<MomentumApp />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole('listitem', { name: 'First' }));
    await screen.findByRole('complementary', { name: 'Task details' });

    const link = await screen.findByRole('link', { name: 'notes.txt' });
    expect(link).toHaveAttribute('href', '/api/v1/attachments/att-1/download');
    expect(screen.getByText('11 B')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Remove notes.txt' }));
    await waitFor(() => expect(screen.queryByText('notes.txt')).toBeNull());
  });
});
