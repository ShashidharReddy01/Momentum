import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { RichTextEditor } from './RichTextEditor';
import type { WriteRequest } from './WritingHelp';

const doc = (text: string) => ({
  type: 'doc',
  content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
});

function setup(help?: (req: WriteRequest) => Promise<string>, editable = true) {
  const onChange = vi.fn();
  render(
    <RichTextEditor
      content={doc('teh launch is delayd')}
      revision={1}
      editable={editable}
      label="Task description"
      placeholder="Describe"
      onChange={onChange}
      writingHelp={help}
    />,
  );
  return { onChange, user: userEvent.setup() };
}

const lastText = (onChange: ReturnType<typeof vi.fn>) =>
  JSON.stringify(onChange.mock.calls.at(-1)?.[0] ?? {});

describe('Writing help (S3.4.4)', () => {
  it('rewrites the whole text when nothing is selected; Replace applies the suggestion', async () => {
    const help = vi.fn(async () => 'The launch is **delayed**.');
    const { user, onChange } = setup(help);
    await user.click(screen.getByRole('button', { name: 'Ask Mo to rewrite' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Fix spelling & grammar' }));
    expect(help).toHaveBeenCalledWith({ action: 'fix_grammar', text: 'teh launch is delayd' });
    const callout = await screen.findByRole('region', { name: /Mo suggests: Fixed spelling/ });
    expect(within(callout).getByLabelText('Suggested text')).toHaveTextContent('The launch is **delayed**.');
    expect(onChange).not.toHaveBeenCalled(); // a suggestion only
    await user.click(within(callout).getByRole('button', { name: 'Replace' }));
    await waitFor(() => expect(lastText(onChange)).toContain('The launch is '));
    expect(lastText(onChange)).toContain('"bold"'); // inserted as Markdown
    expect(lastText(onChange)).not.toContain('teh');
    expect(screen.queryByRole('region', { name: /Mo suggests/ })).toBeNull();
  });

  it('reject leaves the text alone; tone and language are sent', async () => {
    const help = vi.fn(async (req: WriteRequest) => `(${req.action})`);
    const { user, onChange } = setup(help);
    await user.click(screen.getByRole('button', { name: 'Ask Mo to rewrite' }));
    await user.click(await screen.findByRole('menuitem', { name: 'More formal' }));
    await user.click(await screen.findByRole('button', { name: 'Reject' }));
    expect(onChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Ask Mo to rewrite' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Portuguese' }));
    expect(help.mock.calls.map((c) => c[0])).toEqual([
      { action: 'tone', tone: 'formal', text: 'teh launch is delayd' },
      { action: 'translate', language: 'Portuguese', text: 'teh launch is delayd' },
    ]);
  });

  it('an error is shown and Try again asks again for the same text', async () => {
    const help = vi
      .fn<(req: WriteRequest) => Promise<string>>()
      .mockRejectedValueOnce(new Error('Mo is unavailable right now. Try again shortly.'))
      .mockResolvedValueOnce('Shorter.');
    const { user } = setup(help);
    await user.click(screen.getByRole('button', { name: 'Ask Mo to rewrite' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Make shorter' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Mo is unavailable right now');
    // typing meanwhile doesn't change what "Try again" asks about (the same text and range)
    await user.click(screen.getByRole('textbox', { name: 'Task description' }));
    await user.keyboard(' extra');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByLabelText('Suggested text')).toHaveTextContent('Shorter.');
    expect(help.mock.calls[1]![0]).toEqual({ action: 'shorten', text: 'teh launch is delayd' });
  });

  it('never replaces text that changed after asking', async () => {
    let resolve: (s: string) => void = () => {};
    const help = vi.fn(() => new Promise<string>((r) => (resolve = r)));
    const { user, onChange } = setup(help);
    await user.click(screen.getByRole('button', { name: 'Ask Mo to rewrite' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Improve writing' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Mo is rewriting');
    await user.click(screen.getByRole('textbox', { name: 'Task description' }));
    await user.keyboard(' more');
    resolve('Rewritten.');
    await user.click(await screen.findByRole('button', { name: 'Replace' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The text changed since you asked');
    expect(lastText(onChange)).not.toContain('Rewritten.');
  });

  it('no Mo menu without writing help, or when read-only', () => {
    setup(undefined);
    expect(screen.queryByRole('button', { name: 'Ask Mo to rewrite' })).toBeNull();
  });
});
