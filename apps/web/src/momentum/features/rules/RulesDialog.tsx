import { History, MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Dialog } from '@/components/ui/Dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { errorText } from '@/features/ai';
import { useFieldLibrary } from '@/features/fields';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import { useSections } from '@/features/sections';
import { useTagLibrary } from '@/features/tags';
import { useMomentumConfig } from '@/lib/config';
import { RuleBuilder } from './RuleBuilder';
import { RuleRunHistory } from './RuleRunHistory';
import { describeRule, type RuleLookups } from './ruleMeta';
import { useCompileRule, useRuleMutations, useRules, type RuleOut, type RuleSpec } from './queries';

function useSentenceLookups(projectId: string): RuleLookups {
  const people = usePeople();
  const tags = useTagLibrary();
  const sections = useSections(projectId);
  const projects = useProjects();
  const fields = useFieldLibrary();
  return {
    people: new Map((people.data ?? []).map((p) => [p.id, p.name])),
    tags: new Map((tags.data ?? []).map((t) => [t.id, t.name])),
    sections: new Map((sections.data ?? []).map((s) => [s.id, s.name])),
    projects: new Map((projects.data ?? []).map((p) => [p.id, p.name])),
    fields: new Map((fields.data ?? []).map((f) => [f.id, f.name])),
  };
}

function RuleRow({
  rule,
  canEdit,
  lookups,
  editing,
  onEdit,
  onCloseEdit,
}: {
  rule: RuleOut;
  canEdit: boolean;
  lookups: RuleLookups;
  editing: boolean;
  onEdit: () => void;
  onCloseEdit: () => void;
}) {
  const m = useRuleMutations(rule.project_id ?? '');
  const [historyOpen, setHistoryOpen] = useState(false);
  const sentence = describeRule(rule.trigger, rule.conditions, rule.actions, lookups);

  if (editing) {
    return (
      <li className="rounded-md border border-hair-soft">
        <RuleBuilder
          projectId={rule.project_id ?? ''}
          initial={rule}
          saving={m.update.isPending}
          onCancel={onCloseEdit}
          onSave={(spec) => m.update.mutate({ id: rule.id, patch: spec }, { onSuccess: onCloseEdit })}
        />
      </li>
    );
  }

  return (
    <li className="rounded-md border border-hair-soft p-2.5">
      <div className="flex items-center gap-2">
        <button
          type="button"
          role="switch"
          aria-checked={rule.enabled}
          aria-label={rule.enabled ? `Turn off ${rule.name}` : `Turn on ${rule.name}`}
          disabled={!canEdit}
          onClick={() => m.setEnabled.mutate({ id: rule.id, enabled: !rule.enabled })}
          className={`h-5 w-9 shrink-0 rounded-full transition-colors ${rule.enabled ? 'bg-accent' : 'bg-hairline'} disabled:opacity-50`}
        >
          <span
            className={`block h-4 w-4 rounded-full bg-surface shadow transition-transform ${rule.enabled ? 'translate-x-4' : 'translate-x-0.5'}`}
          />
        </button>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{rule.name}</span>
        {canEdit ? (
          <>
            <IconButton
              icon={History}
              label={historyOpen ? `Hide ${rule.name}'s history` : `${rule.name}'s history`}
              size="icon-sm"
              aria-pressed={historyOpen}
              onClick={() => setHistoryOpen((v) => !v)}
            />
            <Button size="sm" variant="ghost" onClick={onEdit}>
              Edit
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton icon={MoreHorizontal} label={`${rule.name} actions`} size="icon-sm" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem className="text-crit" onSelect={() => m.remove.mutate(rule.id)}>
                  <Icon icon={Trash2} /> Delete rule
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        ) : null}
      </div>
      <p className="mt-1 pl-11 text-xs text-muted">{sentence}</p>
      {historyOpen ? (
        <div className="mt-2 border-t border-hair-soft pt-2">
          <RuleRunHistory rule={rule} />
        </div>
      ) : null}
    </li>
  );
}

/** S4.1.4 "describe it": a sentence Mo turns into a draft rule, which then opens in the ordinary
 * builder — prefilled and editable — so nothing is saved without the admin reading it. When Mo
 * can't express the sentence as a rule (Slack, an unknown section, a vague phrase) it asks a
 * question instead of guessing. Hidden while AI is off. */
function DescribeRule({ projectId, onDraft }: { projectId: string; onDraft: (draft: RuleSpec) => void }) {
  const compile = useCompileRule(projectId);
  const [text, setText] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const asked = text.trim();
    if (!asked) return;
    compile.mutate(asked, {
      onSuccess: (r) => {
        if (r.rule) {
          setText('');
          onDraft(r.rule);
        }
      },
    });
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-1.5">
      <div className="flex gap-2">
        <input
          aria-label="Describe a rule"
          placeholder="Describe a rule: when a task moves to Review, assign it to Mei…"
          value={text}
          maxLength={500}
          onChange={(e) => setText(e.target.value)}
          className="h-8 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm outline-none placeholder:text-muted-2 focus:border-focus"
        />
        <Button type="submit" size="sm" variant="ai" loading={compile.isPending} disabled={!text.trim()}>
          <MoMark size={13} /> Draft it
        </Button>
      </div>
      {compile.data?.question ? <AICallout>{compile.data.question}</AICallout> : null}
      {compile.isError ? (
        <p role="alert" className="text-sm text-crit">
          {errorText(compile.error)}
        </p>
      ) : null}
    </form>
  );
}

/** Project "Rules" (⋯ → Rules, S4.1.3): list with enable/disable toggles, an inline builder for
 * creating and editing rules, per-rule run history with a dry-run "test on a task", and (S4.1.4)
 * a box that describes a rule in words for Mo to draft. */
export function RulesDialog({
  projectId,
  canEdit,
  open,
  onOpenChange,
}: {
  projectId: string;
  canEdit: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const rules = useRules(projectId, open);
  const m = useRuleMutations(projectId);
  const lookups = useSentenceLookups(projectId);
  const aiEnabled = useMomentumConfig().ai_enabled;
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<RuleSpec | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const closeBuilder = () => {
    setCreating(false);
    setDraft(null);
  };
  const create = (spec: RuleSpec) => m.create.mutate(spec, { onSuccess: closeBuilder });

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Rules" className="w-[min(640px,calc(100vw-32px))]">
      <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto p-5">
        {rules.isPending ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : (
          <ul aria-label="Rules on this project" className="flex flex-col gap-2">
            {(rules.data ?? []).map((r) => (
              <RuleRow
                key={r.id}
                rule={r}
                canEdit={canEdit}
                lookups={lookups}
                editing={editingId === r.id}
                onEdit={() => setEditingId(r.id)}
                onCloseEdit={() => setEditingId(null)}
              />
            ))}
            {rules.data?.length === 0 && !creating ? (
              <p className="px-1 py-1 text-sm text-muted">No rules on this project yet.</p>
            ) : null}
          </ul>
        )}

        {canEdit ? (
          creating || draft ? (
            <div
              className={
                draft
                  ? 'rounded-md border border-dashed border-amber bg-amber-2/40'
                  : 'rounded-md border border-hair-soft'
              }
            >
              {draft ? (
                <p className="flex items-center gap-1.5 px-4 pt-3 text-xs font-semibold text-amber-ink">
                  <MoMark size={13} /> Mo drafted this from what you typed — check it before saving.
                </p>
              ) : null}
              <RuleBuilder
                key={draft ? 'draft' : 'blank'}
                projectId={projectId}
                draft={draft ?? undefined}
                saving={m.create.isPending}
                onCancel={closeBuilder}
                onSave={create}
              />
            </div>
          ) : (
            <>
              <Button size="sm" variant="ghost" className="justify-start" onClick={() => setCreating(true)}>
                <Icon icon={Plus} /> New rule
              </Button>
              {aiEnabled ? <DescribeRule projectId={projectId} onDraft={setDraft} /> : null}
            </>
          )
        ) : null}
      </div>
    </Dialog>
  );
}
