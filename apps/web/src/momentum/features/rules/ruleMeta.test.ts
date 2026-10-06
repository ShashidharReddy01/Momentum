import { describe, expect, it } from 'vitest';
import { ACTIONS, actionComplete, AI_STEP_KINDS, describeRule, type RuleLookups } from './ruleMeta';
import type { RuleAction } from './queries';

const lookups: RuleLookups = {
  people: new Map([['u1', 'Mei Chen']]),
  tags: new Map(),
  sections: new Map([['s1', 'Review']]),
  projects: new Map(),
  fields: new Map([['f1', 'Risk']]),
  forms: new Map(),
};

describe('AI step metadata (S4.1.5)', () => {
  it('offers every kind the backend accepts, and no action the backend refuses', () => {
    expect(AI_STEP_KINDS.map((k) => k.kind)).toEqual([
      'summarize_to_comment',
      'draft_reply',
      'classify_field',
      'extract_fields',
    ]);
    expect(ACTIONS.map((a) => a.type)).toContain('ai_step');
    expect(ACTIONS.map((a) => a.type)).not.toContain('slack_message');
  });

  it('only classify_field needs a field before the rule can be saved', () => {
    expect(actionComplete({ type: 'ai_step', kind: 'summarize_to_comment' })).toBe(true);
    expect(actionComplete({ type: 'ai_step', kind: 'classify_field' })).toBe(false);
    expect(actionComplete({ type: 'ai_step', kind: 'classify_field', field_id: 'priority' })).toBe(true);
    expect(actionComplete({ type: 'ai_step' })).toBe(false);
  });

  it('reads each kind back in words', () => {
    const sentence = (action: RuleAction) =>
      describeRule({ type: 'task.moved', to_section: 's1' }, [], [action], lookups);
    expect(sentence({ type: 'ai_step', kind: 'summarize_to_comment' })).toContain(
      'let Mo post a summary of the comments',
    );
    expect(sentence({ type: 'ai_step', kind: 'draft_reply' })).toContain('let Mo draft a reply comment');
    expect(sentence({ type: 'ai_step', kind: 'classify_field', field_id: 'f1' })).toContain(
      'let Mo set Risk from what the task says',
    );
    expect(sentence({ type: 'ai_step', kind: 'extract_fields' })).toContain(
      'let Mo fill in the empty fields',
    );
  });
});

describe('task.unblocked trigger (S6.1.3)', () => {
  it('is offered and reads back in words', async () => {
    const { TRIGGERS } = await import('./ruleMeta');
    expect(TRIGGERS.map((t) => t.type)).toContain('task.unblocked');
    expect(describeRule({ type: 'task.unblocked' }, [], [{ type: 'mark_complete' }], lookups)).toContain(
      "a task's last blocker is completed",
    );
  });
});

describe('set_project_field and the title/type conditions (Phase 7.5)', () => {
  const stage = {
    id: 'pf-stage',
    name: 'Stage',
    type: 'single_select' as const,
    options: [
      { id: 'o-disc', label: 'Discovery', color: 'blue', archived: false },
      { id: 'o-impl', label: 'Implementation', color: 'green', archived: false },
    ],
    description: null,
    is_library: true,
    created_by: null,
    applies_to: 'project' as const,
  };
  const withStage: RuleLookups = { ...lookups, projectFields: new Map([[stage.id, stage]]) };

  it('reads back with the choice label, and needs a value (false and 0 count)', async () => {
    const { CONDITION_FIELDS } = await import('./ruleMeta');
    expect(CONDITION_FIELDS).toContain('title');
    expect(CONDITION_FIELDS).toContain('type');
    const sentence = describeRule(
      { type: 'task.completed' },
      [{ field: 'title', op: 'eq', value: 'Contract signed' }],
      [{ type: 'set_project_field', field_id: 'pf-stage', value: 'o-impl' }],
      withStage,
    );
    expect(sentence).toBe(
      "When a task is completed, if title is Contract signed, then set the project's Stage to Implementation.",
    );
    expect(actionComplete({ type: 'set_project_field', field_id: 'pf-stage' })).toBe(false);
    expect(actionComplete({ type: 'set_project_field', field_id: 'pf-stage', value: 'o-impl' })).toBe(true);
    expect(actionComplete({ type: 'set_project_field', field_id: 'pf-signed', value: false })).toBe(true);
    expect(actionComplete({ type: 'set_project_field', field_id: 'pf-n', value: 0 })).toBe(true);
  });
});
