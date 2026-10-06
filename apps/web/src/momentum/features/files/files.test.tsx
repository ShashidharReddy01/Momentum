import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { fileHandlers, mockFile, type MockFile } from '@/mocks/files';
import { notificationHandlers } from '@/mocks/notifications';
import { authHandlers } from '@/mocks/handlers';
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

// jsdom's File/FormData can't cross MSW's interceptor (see tasks/attachments.test.tsx), so the
// multipart body is replaced by a URL-encoded one carrying the file name: the request, its route
// and its replace_id are real, only the bytes are left out.
class FormDataStandIn extends URLSearchParams {
  override append(name: string, value: string | Blob): void {
    super.append(name, typeof value === 'string' ? value : (value as File).name);
  }
}
vi.stubGlobal('FormData', FormDataStandIn);

function boot(files: MockFile[], role = 'admin') {
  const f = fileHandlers(files);
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: role }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...notificationHandlers(),
  );
  server.use(...f.handlers);
  window.history.replaceState(null, '', '/projects/seed-1/files');
  render(<MomentumApp />);
  return { ...f, user: userEvent.setup() };
}

const FILES = [
  mockFile({ id: 'f1', filename: 'Statement of work.docx', location: { type: 'project' } }),
  mockFile({
    id: 'f2',
    filename: 'Quote.xlsx',
    location: { type: 'task', task_id: 't1', task_key: 'T-7', task_title: 'Send the quote' },
  }),
  mockFile({
    id: 'f3',
    filename: 'screenshot.png',
    location: {
      type: 'comment',
      task_id: 't1',
      task_key: 'T-7',
      task_title: 'Send the quote',
      comment_id: 'c1',
    },
  }),
];

describe('Files tab (Phase 7.5)', () => {
  it('lists every file with where it lives, and filters by kind and search', async () => {
    const { user } = boot(FILES);
    const grid = await screen.findByRole('grid', { name: 'Project files' });
    expect(within(grid).getByText('Statement of work.docx')).toBeInTheDocument();
    expect(within(grid).getByText('Quote.xlsx')).toBeInTheDocument();
    expect(within(grid).getAllByText(/Send the quote/)).toHaveLength(2);
    expect(within(grid).getByText(/\(comment\)/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Kind'), 'spreadsheet');
    await waitFor(() => expect(screen.queryByText('Statement of work.docx')).not.toBeInTheDocument());
    expect(screen.getByText('Quote.xlsx')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Kind'), '');
    await user.type(screen.getByLabelText('Search files'), 'statement');
    await waitFor(() => expect(screen.queryByText('Quote.xlsx')).not.toBeInTheDocument());
    expect(await screen.findByText('Statement of work.docx')).toBeInTheDocument();
  });

  it('rows are a grid with roving focus; Enter opens the preview', async () => {
    const { user } = boot(FILES);
    const rows = (await screen.findAllByRole('row')).slice(1);
    expect(rows[0]).toHaveAttribute('tabindex', '0');
    expect(rows[1]).toHaveAttribute('tabindex', '-1');
    rows[0]!.focus();
    await user.keyboard('{ArrowDown}');
    expect(rows[1]).toHaveFocus();
    await user.keyboard('{Enter}');
    const panel = await screen.findByRole('complementary', { name: 'File preview' });
    expect(within(panel).getByText('Quote.xlsx')).toBeInTheDocument();
    expect(within(panel).getByText('No preview for this kind of file.')).toBeInTheDocument();
  });

  it('uploads, and offers a new version when the name matches a project file', async () => {
    const { user, uploads } = boot(FILES);
    await screen.findByRole('grid', { name: 'Project files' });
    const input = screen.getByTestId('files-upload-input') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['a'], 'notes.txt', { type: 'text/plain' })] } });
    await waitFor(() => expect(uploads).toEqual([{ name: 'notes.txt', replace_id: null }]));
    expect(await screen.findByText('notes.txt')).toBeInTheDocument();

    fireEvent.change(input, {
      target: { files: [new File(['b'], 'Statement of work.docx', { type: 'text/plain' })] },
    });
    const dialog = await screen.findByRole('dialog', { name: /new version of Statement of work.docx/ });
    await user.click(within(dialog).getByRole('button', { name: 'New version' }));
    await waitFor(() => expect(uploads[1]).toEqual({ name: 'Statement of work.docx', replace_id: 'f1' }));
    expect(await screen.findByText('v2')).toBeInTheDocument();
  });

  it('deletes with an Undo toast', async () => {
    const { user, deleted } = boot(FILES);
    await screen.findByRole('grid', { name: 'Project files' });
    await user.click(screen.getByRole('button', { name: 'Actions for Quote.xlsx' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    await waitFor(() => expect(deleted).toEqual(['f2']));
    expect(await screen.findByText('Deleted Quote.xlsx')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Undo' }).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.queryByText('Quote.xlsx')).not.toBeInTheDocument());
  });

  it('a viewer sees the files but no Upload', async () => {
    boot(FILES, 'viewer');
    await screen.findByRole('grid', { name: 'Project files' });
    expect(screen.queryByRole('button', { name: 'Upload' })).not.toBeInTheDocument();
  });

  it('says so when there are no files', async () => {
    boot([]);
    expect(await screen.findByText('No files yet')).toBeInTheDocument();
    expect(screen.getByText(/Files attached to tasks and comments show up here too/)).toBeInTheDocument();
  });
});
