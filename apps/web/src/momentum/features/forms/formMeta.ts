import type { ProjectField } from '@/features/fields';
import type { Person } from '@/features/people';
import type { RenderQuestion } from './FormFiller';
import type { Question } from './queries';

/** Mirrors `domain/forms/schemas.py`'s `FIXED_TARGETS`. */
export const FIXED_TARGETS: { id: string; label: string }[] = [
  { id: 'title', label: 'Task title' },
  { id: 'description', label: 'Description' },
  { id: 'assignee', label: 'Assignee' },
  { id: 'due_on', label: 'Due date' },
  { id: 'priority', label: 'Priority' },
];

export const MAX_QUESTIONS = 20;

export function newQuestionId(existing: Question[]): string {
  const ids = new Set(existing.map((q) => q.id));
  let n = 1;
  while (ids.has(`q${n}`)) n += 1;
  return `q${n}`;
}

export function titleQuestion(questions: Question[]): Question | undefined {
  return questions.find((q) => q.maps_to === 'title');
}

const PRIORITY_OPTIONS = ['urgent', 'high', 'medium', 'low'].map((p) => ({
  id: p,
  label: p[0]!.toUpperCase() + p.slice(1),
}));

/** The internal (logged-in) fill page has no server-rendered question shape (only the public
 * link gets one, from `service.public_form_view`), so it derives the same widget kind
 * client-side from the project's own fields and members — the small mirror of
 * `domain/forms/service._question_view` the frontend needs. */
export function renderQuestions(
  questions: Question[],
  fields: ProjectField[],
  people: Person[],
): RenderQuestion[] {
  const fieldsById = new Map(fields.map((pf) => [pf.field.id, pf.field]));
  return questions.map((q): RenderQuestion => {
    const base = {
      id: q.id,
      label: q.label,
      help_text: q.help_text,
      required: q.required,
      show_if: q.show_if,
    };
    if (q.maps_to === 'title') return { ...base, kind: 'short_text' };
    if (q.maps_to === 'description') return { ...base, kind: 'long_text' };
    if (q.maps_to === 'due_on') return { ...base, kind: 'date' };
    if (q.maps_to === 'priority') return { ...base, kind: 'select', options: PRIORITY_OPTIONS };
    if (q.maps_to === 'assignee')
      return { ...base, kind: 'person', people: people.map((p) => ({ id: p.id, label: p.name })) };
    const field = fieldsById.get(q.maps_to);
    if (!field) return { ...base, kind: 'short_text' };
    if (field.type === 'text' || field.type === 'url') return { ...base, kind: 'short_text' };
    if (field.type === 'number' || field.type === 'currency' || field.type === 'percent')
      return { ...base, kind: 'number' };
    if (field.type === 'date') return { ...base, kind: 'date' };
    if (field.type === 'checkbox') return { ...base, kind: 'checkbox' };
    const selectOptions = Array.isArray(field.options) ? field.options : [];
    const options = selectOptions.filter((o) => !o.archived).map((o) => ({ id: o.id, label: o.label }));
    return { ...base, kind: field.type === 'multi_select' ? 'multi_select' : 'select', options };
  });
}

/** A question is complete enough to save: it has a label and (unless it's the always-visible
 * title question) doesn't depend on itself or a question that comes after it. */
export function questionsValid(questions: Question[]): boolean {
  if (questions.length === 0) return false;
  const titles = questions.filter((q) => q.maps_to === 'title');
  if (titles.length !== 1 || !titles[0]!.required || titles[0]!.show_if) return false;
  const seenTargets = new Set<string>();
  const index = new Map(questions.map((q, i) => [q.id, i]));
  for (const [i, q] of questions.entries()) {
    if (!q.label.trim()) return false;
    if (seenTargets.has(q.maps_to)) return false;
    seenTargets.add(q.maps_to);
    if (q.show_if) {
      const dep = index.get(q.show_if.question_id);
      if (dep === undefined || dep >= i) return false;
    }
  }
  return true;
}
