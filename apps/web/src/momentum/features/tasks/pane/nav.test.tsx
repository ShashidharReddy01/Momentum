import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { TaskNavProvider, useTaskNav } from './nav';

function Probe() {
  const nav = useTaskNav()!;
  return (
    <div>
      <span data-testid="open">{nav.openId ?? 'none'}</span>
      <input aria-label="Field" />
      <button type="button">Row</button>
    </div>
  );
}

const boot = () =>
  render(
    <MemoryRouter initialEntries={['/projects/p1/list?task=t1']}>
      <TaskNavProvider>
        <Probe />
      </TaskNavProvider>
    </MemoryRouter>,
  );

afterEach(cleanup);

describe('task pane navigation (Phase 6.5 keyboard pass)', () => {
  it('Escape closes the open task even when focus is on the list, not in the pane', () => {
    boot();
    expect(screen.getByTestId('open')).toHaveTextContent('t1');
    screen.getByRole('button', { name: 'Row' }).focus();
    act(() => void fireEvent.keyDown(screen.getByRole('button', { name: 'Row' }), { key: 'Escape' }));
    expect(screen.getByTestId('open')).toHaveTextContent('none');
  });

  it('leaves Escape to a text field', () => {
    boot();
    const field = screen.getByRole('textbox', { name: 'Field' });
    act(() => void fireEvent.keyDown(field, { key: 'Escape' }));
    expect(screen.getByTestId('open')).toHaveTextContent('t1');
  });
});
