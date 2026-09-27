import type { RuleAction, RuleCondition, RuleTrigger } from './queries';

/** Mirrors `domain/rules/schemas.py`'s `TRIGGER_PARAMS` (minus `NOT_YET_TRIGGERS`, which the API
 * refuses to save). Kept in sync by hand since the schema isn't exposed as picker metadata. */
export const TRIGGERS: { type: string; label: string; params: string[] }[] = [
  { type: 'task.added', label: 'A task is added to this project', params: [] },
  { type: 'task.moved', label: 'A task moves to a section', params: ['to_section'] },
  { type: 'task.field_changed', label: "A task's field changes", params: ['field', 'to'] },
  { type: 'task.completed', label: 'A task is completed', params: [] },
  { type: 'task.assigned', label: 'A task is assigned', params: ['user_id'] },
  { type: 'task.due_approaching', label: "A task's due date is approaching", params: [] },
];

export const TRIGGER_FIELDS = ['priority', 'due_on', 'start_on'] as const;
export const CONDITION_FIELDS = ['priority', 'assignee', 'due_on', 'start_on', 'tag'] as const;
export const OPS: { op: string; label: string; needsValue: boolean }[] = [
  { op: 'eq', label: 'is', needsValue: true },
  { op: 'neq', label: 'is not', needsValue: true },
  { op: 'in', label: 'is one of', needsValue: true },
  { op: 'gt', label: 'is after/greater than', needsValue: true },
  { op: 'lt', label: 'is before/less than', needsValue: true },
  { op: 'empty', label: 'is empty', needsValue: false },
  { op: 'not_empty', label: 'is not empty', needsValue: false },
];

/** Mirrors `ACTION_PARAMS`/`ACTION_REQUIRED` (minus `NOT_YET_ACTIONS`: `slack_message` is refused
 * on write until P7, so the builder doesn't offer it). */
export const ACTIONS: { type: string; label: string; params: string[]; required: string[] }[] = [
  { type: 'assign', label: 'Assign to', params: ['user_id'], required: ['user_id'] },
  { type: 'add_comment', label: 'Add a comment', params: ['text'], required: ['text'] },
  { type: 'move_section', label: 'Move to section', params: ['section_id'], required: ['section_id'] },
  { type: 'mark_complete', label: 'Mark complete', params: [], required: [] },
  { type: 'set_field', label: 'Set a field', params: ['field_id', 'value'], required: ['field_id', 'value'] },
  {
    type: 'add_to_project',
    label: 'Add to another project',
    params: ['project_id', 'section_id'],
    required: ['project_id'],
  },
  {
    type: 'remove_from_project',
    label: 'Remove from a project',
    params: ['project_id'],
    required: ['project_id'],
  },
  { type: 'add_tag', label: 'Add a tag', params: ['tag_id'], required: ['tag_id'] },
  { type: 'create_subtasks', label: 'Create subtasks', params: ['titles'], required: ['titles'] },
  { type: 'set_due_relative', label: 'Set a relative due date', params: ['days'], required: ['days'] },
  { type: 'notify_user', label: 'Notify someone', params: ['user_id', 'text'], required: ['text'] },
  { type: 'ai_step', label: 'Let Mo do a step (AI)', params: ['kind', 'field_id'], required: ['kind'] },
];

/** S4.1.5 `AI_STEP_KINDS`: what the AI step does. `classify_field` is the only one that takes a
 * field. The step runs on the AI queue just after the rule, and its writes are marked as AI. */
export const AI_STEP_KINDS: { kind: string; label: string; needsField: boolean }[] = [
  { kind: 'summarize_to_comment', label: 'Summarize the comments into a comment', needsField: false },
  { kind: 'draft_reply', label: 'Draft a reply to the newest comment', needsField: false },
  { kind: 'classify_field', label: 'Set a field from what the task says', needsField: true },
  { kind: 'extract_fields', label: 'Fill in the empty fields from the description', needsField: false },
];

/** Whether an action has everything it needs to be saved (`required`, plus the AI step's field). */
export function actionComplete(a: RuleAction): boolean {
  const meta = ACTIONS.find((m) => m.type === a.type);
  if (!meta) return false;
  const values = a as unknown as Record<string, unknown>;
  if (!meta.required.every((p) => values[p])) return false;
  return !(a.type === 'ai_step' && a.kind === 'classify_field' && !a.field_id);
}

export function defaultTrigger(type: string): RuleTrigger {
  return { type };
}

export function defaultCondition(): RuleCondition {
  return { field: 'priority', op: 'eq', value: '' };
}

export function defaultAction(type: string): RuleAction {
  if (type === 'set_due_relative') return { type, days: 1 };
  if (type === 'create_subtasks') return { type, titles: [''] };
  if (type === 'ai_step') return { type, kind: 'summarize_to_comment' };
  return { type };
}

export interface RuleLookups {
  people: Map<string, string>;
  tags: Map<string, string>;
  sections: Map<string, string>;
  projects: Map<string, string>;
  fields: Map<string, string>;
}

const person = (l: RuleLookups, id: string | null | undefined) =>
  id ? (l.people.get(id) ?? 'someone') : 'no one';
const fieldName = (l: RuleLookups, id: string | null | undefined) => {
  if (!id) return 'a field';
  if (id === 'priority' || id === 'due_on' || id === 'start_on') return id.replace('_', ' ');
  return l.fields.get(id) ?? 'a custom field';
};

function describeTrigger(t: RuleTrigger, l: RuleLookups): string {
  switch (t.type) {
    case 'task.added':
      return 'a task is added to this project';
    case 'task.moved':
      return t.to_section
        ? `a task moves to ${l.sections.get(t.to_section) ?? 'a section'}`
        : 'a task moves section';
    case 'task.field_changed':
      return t.to !== undefined && t.to !== null
        ? `${fieldName(l, t.field)} changes to ${JSON.stringify(t.to)}`
        : `${fieldName(l, t.field)} changes`;
    case 'task.completed':
      return 'a task is completed';
    case 'task.assigned':
      return t.user_id ? `a task is assigned to ${person(l, t.user_id)}` : 'a task is assigned';
    case 'task.due_approaching':
      return "a task's due date is tomorrow";
    default:
      return t.type;
  }
}

function describeCondition(c: RuleCondition, l: RuleLookups): string {
  const field = c.field === 'assignee' ? 'assignee' : c.field === 'tag' ? 'tag' : fieldName(l, c.field);
  const opLabel = OPS.find((o) => o.op === c.op)?.label ?? c.op;
  if (c.op === 'empty' || c.op === 'not_empty') return `${field} ${opLabel}`;
  const rawValues = Array.isArray(c.value) ? c.value : [c.value];
  const values = rawValues
    .map((v) => {
      if (typeof v !== 'string') return JSON.stringify(v);
      if (c.field === 'assignee') return person(l, v);
      if (c.field === 'tag') return l.tags.get(v) ?? v;
      return v;
    })
    .join(', ');
  return `${field} ${opLabel} ${values}`;
}

function describeAction(a: RuleAction, l: RuleLookups): string {
  switch (a.type) {
    case 'assign':
      return `assign to ${person(l, a.user_id)}`;
    case 'add_comment':
      return `comment "${a.text ?? ''}"`;
    case 'move_section':
      return `move to ${a.section_id ? (l.sections.get(a.section_id) ?? 'a section') : 'a section'}`;
    case 'mark_complete':
      return 'mark complete';
    case 'set_field':
      return `set ${fieldName(l, a.field_id)} to ${JSON.stringify(a.value)}`;
    case 'add_to_project':
      return `add to ${a.project_id ? (l.projects.get(a.project_id) ?? 'another project') : 'another project'}`;
    case 'remove_from_project':
      return `remove from ${a.project_id ? (l.projects.get(a.project_id) ?? 'that project') : 'that project'}`;
    case 'add_tag':
      return `add tag ${a.tag_id ? (l.tags.get(a.tag_id) ?? 'a tag') : 'a tag'}`;
    case 'create_subtasks':
      return `create subtasks: ${(a.titles ?? []).filter(Boolean).join(', ') || '…'}`;
    case 'set_due_relative':
      return `set the due date to ${a.days ?? 0} day${a.days === 1 ? '' : 's'} from now`;
    case 'notify_user':
      return `notify ${person(l, a.user_id)}: "${a.text ?? ''}"`;
    case 'ai_step':
      switch (a.kind) {
        case 'summarize_to_comment':
          return 'let Mo post a summary of the comments';
        case 'draft_reply':
          return 'let Mo draft a reply comment';
        case 'classify_field':
          return `let Mo set ${fieldName(l, a.field_id)} from what the task says`;
        case 'extract_fields':
          return 'let Mo fill in the empty fields from the description';
        default:
          return 'let Mo do a step';
      }
    default:
      return a.type;
  }
}

/** A readable sentence for the builder's live preview and the rule list row, e.g. "When a task
 * moves to Review, if priority is high, then assign to Mei, add tag Escalated." */
export function describeRule(
  trigger: RuleTrigger,
  conditions: RuleCondition[],
  actions: RuleAction[],
  lookups: RuleLookups,
): string {
  const parts = [`When ${describeTrigger(trigger, lookups)}`];
  if (conditions.length)
    parts.push(`if ${conditions.map((c) => describeCondition(c, lookups)).join(' and ')}`);
  parts.push(`then ${actions.map((a) => describeAction(a, lookups)).join(', ') || '…'}`);
  return `${parts.join(', ')}.`;
}
