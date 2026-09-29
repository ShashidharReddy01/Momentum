import { describe, expect, it } from 'vitest';
import { assignedMessage } from './AssigneePicker';

describe('assignedMessage (S5.2.1)', () => {
  it('says an agent will answer in the comments', () => {
    expect(assignedMessage({ id: 'a', name: 'Teammate', is_agent: true }, 'me')).toBe(
      'Assigned to Teammate. It will reply in the comments shortly.',
    );
  });
  it('keeps the plain messages for people', () => {
    expect(assignedMessage({ id: 'me', name: 'Ravi' }, 'me')).toBe('Assigned to you');
    expect(assignedMessage({ id: 'x', name: 'Ana' }, 'me')).toBe('Assigned to Ana');
    expect(assignedMessage(null, 'me')).toBe('Unassigned');
  });
});
