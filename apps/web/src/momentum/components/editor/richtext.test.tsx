import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { RichTextView } from './RichTextView';

const doc = (...content: object[]) => ({ type: 'doc', content });
const p = (...content: object[]) => ({ type: 'paragraph', content });
const t = (text: string, marks?: object[]) => ({ type: 'text', text, ...(marks ? { marks } : {}) });

describe('RichTextView', () => {
  it('renders marks, lists, checklists and mentions', () => {
    render(
      <MemoryRouter>
        <RichTextView
          personName={(id) => (id === 'u1' ? 'Ana Souza' : undefined)}
          doc={doc(
            p(t('bold', [{ type: 'bold' }]), t(' and '), t('code', [{ type: 'code' }])),
            { type: 'bulletList', content: [{ type: 'listItem', content: [p(t('item'))] }] },
            {
              type: 'taskList',
              content: [{ type: 'taskItem', attrs: { checked: true }, content: [p(t('done'))] }],
            },
            p({ type: 'mention', attrs: { id: 'u1', label: 'Old name', kind: 'user' } }, t(' see '), {
              type: 'mention',
              attrs: { id: 't1', label: 'Spec task', kind: 'task' },
            }),
          )}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('bold').tagName).toBe('STRONG');
    expect(screen.getByText('code').tagName).toBe('CODE');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByRole('checkbox')).toBeChecked();
    expect(screen.getByText('@Ana Souza')).toBeInTheDocument(); // current name, not the stored label
    expect(screen.getByRole('link', { name: 'Spec task' })).toHaveAttribute('href', '/task/t1');
  });

  it('never renders unsafe links or unknown markup', () => {
    const { container } = render(
      <MemoryRouter>
        <RichTextView
          doc={doc(
            p(t('bad', [{ type: 'link', attrs: { href: 'javascript:alert(1)' } }])),
            p(t('ok', [{ type: 'link', attrs: { href: 'https://example.test' } }])),
            { type: 'iframe', content: [p(t('inside'))] },
            p(t('<img src=x onerror=alert(1)>')),
          )}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('bad').closest('a')).toBeNull();
    const ok = screen.getByRole('link', { name: 'ok' });
    expect(ok).toHaveAttribute('rel', 'noopener noreferrer nofollow');
    expect(container.querySelector('iframe, img, script')).toBeNull();
    expect(screen.getByText('inside')).toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument(); // shown as text
  });
});
