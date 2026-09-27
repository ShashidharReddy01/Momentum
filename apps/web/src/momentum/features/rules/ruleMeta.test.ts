import { describe, expect, it } from 'vitest';
import { ACTIONS, actionComplete, AI_STEP_KINDS, describeRule, type RuleLookups } from './ruleMeta';
import type { RuleAction } from './queries';

const lookups: RuleLookups = {
  people: new Map([['u1', 'Mei Chen']]),
  tags: new Map(),
  sections: new Map([['s1', 'Review']]),
  projects: new Map(),
  fields: new Map([['f1', 'Risk']]),
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
