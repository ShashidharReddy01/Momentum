import { describe, expect, it } from 'vitest';
import type { ProjectField } from '@/features/fields';
import type { Person } from '@/features/people';
import { newQuestionId, questionsValid, renderQuestions } from './formMeta';
import type { Question } from './queries';

const title: Question = { id: 'q1', label: 'Title', required: true, maps_to: 'title' };

describe('questionsValid (S4.2.1)', () => {
  it('needs exactly one required, unconditional title question', () => {
    expect(questionsValid([])).toBe(false);
    expect(questionsValid([{ ...title, required: false }])).toBe(false);
    expect(questionsValid([{ ...title, show_if: { question_id: 'q0', equals: 'x' } }])).toBe(false);
    expect(questionsValid([title])).toBe(true);
    expect(questionsValid([title, { id: 'q2', label: 'Again', required: true, maps_to: 'title' }])).toBe(
      false,
    );
  });

  it('rejects a blank label, a repeated target, or branching on a later question', () => {
    expect(questionsValid([title, { id: 'q2', label: '', required: false, maps_to: 'description' }])).toBe(
      false,
    );
    expect(
      questionsValid([
        title,
        { id: 'q2', label: 'A', required: false, maps_to: 'description' },
        { id: 'q3', label: 'B', required: false, maps_to: 'description' },
      ]),
    ).toBe(false);
    expect(
      questionsValid([
        title,
        {
          id: 'q2',
          label: 'A',
          required: false,
          maps_to: 'description',
          show_if: { question_id: 'q3', equals: 'x' },
        },
        { id: 'q3', label: 'B', required: false, maps_to: 'due_on' },
      ]),
    ).toBe(false);
  });
});

describe('newQuestionId', () => {
  it('picks the first unused qN', () => {
    expect(newQuestionId([])).toBe('q1');
    expect(newQuestionId([title])).toBe('q2');
    expect(newQuestionId([{ ...title, id: 'q2' }])).toBe('q1');
    expect(newQuestionId([title, { ...title, id: 'q2' }])).toBe('q3');
  });
});

describe('renderQuestions (internal fill page)', () => {
  const fields: ProjectField[] = [
    {
      position: 'a',
      is_visible: true,
      field: {
        id: 'f1',
        name: 'Kind',
        type: 'single_select',
        options: [{ id: 'o1', label: 'Bug', color: 'red', archived: false }],
        description: null,
        is_library: true,
        created_by: null,
      },
    },
  ];
  const people: Person[] = [
    {
      id: 'u1',
      name: 'Mei Chen',
      email: 'mei@acme.test',
      role: 'member',
      is_agent: false,
      timezone: 'UTC',
      status: 'active',
      avatar_url: null,
    },
  ];

  it('derives the same widget kind the public endpoint would', () => {
    const [rTitle, rAssignee, rField] = renderQuestions(
      [
        title,
        { id: 'q2', label: 'Owner', required: false, maps_to: 'assignee' },
        { id: 'q3', label: 'Kind', required: false, maps_to: 'f1' },
      ],
      fields,
      people,
    );
    expect(rTitle!.kind).toBe('short_text');
    expect(rAssignee!.kind).toBe('person');
    expect(rAssignee!.people).toEqual([{ id: 'u1', label: 'Mei Chen' }]);
    expect(rField!.kind).toBe('select');
    expect(rField!.options).toEqual([{ id: 'o1', label: 'Bug' }]);
  });
});
