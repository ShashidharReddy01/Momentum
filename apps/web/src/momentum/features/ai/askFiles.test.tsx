import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { fireEvent } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiChatHandlers, aiCommandHandlers } from '@/mocks/ai';
import { fileHandlers, mockFile } from '@/mocks/files';
import { authHandlers } from '@/mocks/handlers';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => {
  server.close();
  vi.unstubAllGlobals();
});
// jsdom's File/FormData can't cross MSW (see files.test.tsx): a URL-encoded stand-in carries
// the file name, so the routes and the fallback are real.
class FormDataStandIn extends URLSearchParams {
  override append(name: string, value: string | Blob): void {
    super.append(name, typeof value === 'string' ? value : (value as File).name);
  }
}
vi.stubGlobal('FormData', FormDataStandIn);

const ANSWER: [string, Record<string, unknown>][] = [
  ['conversation', { conversation_id: 'conv-1', user_message_id: 'm-1' }],
  ['tool_call', { id: 'c1', name: 'query_table' }],
  ['tool_result', { id: 'c1', name: 'query_table', ok: true, summary: 'Queried s:Quote', preview: false }],
  ['token', { text: 'The quote totals 51000 [F:Quote.xlsx · s:Quote].' }],
  [
    'citation',
    {
      ref: '[F:Quote.xlsx · s:Quote]',
      type: 'file',
      valid: true,
      id: 'f2',
      key: 's:Quote',
      title: 'Quote.xlsx',
    },
  ],
  ['done', { steps: 2, message_id: 'm-2', grounded: false, images: 0 }],
];

function boot(role = 'admin') {
  const chat = aiChatHandlers([ANSWER, ANSWER]);
  const files = fileHandlers([
    mockFile({ id: 'f1', filename: 'Statement of work.docx' }),
    mockFile({ id: 'f2', filename: 'Quote.xlsx' }),
  ]);
  const uploads: string[] = [];
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: role }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...notificationHandlers(),
    ...chat.handlers,
    ...aiCommandHandlers([]).handlers,
  );
  server.use(...files.handlers);
  server.use(
    http.post('*/api/v1/projects/:pid/files', () =>
      role === 'viewer'
        ? HttpResponse.json({ title: 'Forbidden', status: 403, code: 'forbidden' }, { status: 403 })
        : HttpResponse.json(
            {
              data: { id: 'f9', filename: 'notes.txt', task_id: null, comment_id: null },
              meta: { activity_id: null, batch_id: null },
            },
            { status: 201 },
          ),
    ),
    http.post('*/api/v1/ai/conversation-files', async ({ request }) => {
      const form = await request.formData();
      uploads.push(String(form.get('file')));
      return HttpResponse.json(
        {
          id: 'cf-1',
          conversation_id: 'conv-7',
          filename: String(form.get('file')),
          mime: 'text/plain',
          size_bytes: 3,
          created_at: '2026-10-06T10:00:00Z',
        },
        { status: 201 },
      );
    }),
  );
  window.history.replaceState(null, '', '/projects/seed-1/files');
  render(<MomentumApp />);
  return { user: userEvent.setup(), chat, uploads };
}

const panel = () => screen.getByRole('complementary', { name: 'Ask Mo' });

describe('Ask Mo about files (Phase 7.5)', () => {
  it('from the Files tab: the file goes with the question; the answer shows a locator chip', async () => {
    const { user, chat } = boot();
    await screen.findByRole('grid', { name: 'Project files' });
    await user.click(screen.getByRole('button', { name: 'Actions for Quote.xlsx' }));
    await user.click(await screen.findByRole('menuitem', { name: /Ask Mo about this file/ }));
    await screen.findByRole('complementary', { name: 'Ask Mo' });
    expect(await within(panel()).findByLabelText('Chat is about Quote.xlsx')).toBeInTheDocument();
    await user.click(within(panel()).getByRole('button', { name: 'Summarize this file' }));
    await waitFor(() => expect(chat.requests).toHaveLength(1));
    expect(chat.requests[0]!.screen).toEqual({ kind: 'project', project_id: 'seed-1', file_ids: ['f2'] });
    const chip = await within(panel()).findByRole('link', { name: 'File Quote.xlsx · s:Quote' });
    expect(chip).toHaveAttribute('href', '/api/v1/attachments/f2/download');
    expect(within(panel()).getByText(/Queried a table/)).toBeInTheDocument();
  });

  it("the paperclip: a viewer's file goes to the chat only, which the next question continues", async () => {
    const { user, chat, uploads } = boot('viewer');
    await screen.findByRole('grid', { name: 'Project files' });
    await user.keyboard('{Control>}j{/Control}');
    await screen.findByRole('complementary', { name: 'Ask Mo' });
    const input = within(panel()).getByTestId('mo-attach-input');
    fireEvent.change(input, { target: { files: [new File(['abc'], 'notes.txt', { type: 'text/plain' })] } });
    const files = await within(panel()).findByRole('group', { name: 'Files in this chat' });
    expect(await within(files).findByText('notes.txt')).toBeInTheDocument();
    expect(uploads).toEqual(['notes.txt']);
    await user.type(within(panel()).getByRole('textbox', { name: 'Message Mo' }), 'What is in it?{Enter}');
    await waitFor(() => expect(chat.requests).toHaveLength(1));
    expect(chat.requests[0]!.conversation_id).toBe('conv-7');
  });

  it("the paperclip: an editor's file goes to the project and rides as a chip", async () => {
    const { user, chat, uploads } = boot('admin');
    await screen.findByRole('grid', { name: 'Project files' });
    await user.keyboard('{Control>}j{/Control}');
    await screen.findByRole('complementary', { name: 'Ask Mo' });
    fireEvent.change(within(panel()).getByTestId('mo-attach-input'), {
      target: { files: [new File(['abc'], 'notes.txt', { type: 'text/plain' })] },
    });
    expect(
      await within(panel()).findByRole('button', { name: 'Remove notes.txt from this chat' }),
    ).toBeInTheDocument();
    expect(uploads).toEqual([]);
    await user.type(within(panel()).getByRole('textbox', { name: 'Message Mo' }), 'Summarise it{Enter}');
    await waitFor(() => expect(chat.requests).toHaveLength(1));
    expect((chat.requests[0]!.screen as { file_ids?: string[] }).file_ids).toEqual(['f9']);
  });
});
