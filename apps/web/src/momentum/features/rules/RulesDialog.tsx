import { History, MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
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
import { useFieldLibrary } from '@/features/fields';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import { useSections } from '@/features/sections';
import { useTagLibrary } from '@/features/tags';
import { RuleBuilder } from './RuleBuilder';
import { RuleRunHistory } from './RuleRunHistory';
import { describeRule, type RuleLookups } from './ruleMeta';
import { useRuleMutations, useRules, type RuleOut, type RuleSpec } from './queries';

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

/** Project "Rules" (⋯ → Rules, S4.1.3): list with enable/disable toggles, an inline builder for
 * creating and editing rules, and per-rule run history with a dry-run "test on a task". */
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
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const create = (spec: RuleSpec) => m.create.mutate(spec, { onSuccess: () => setCreating(false) });

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
          creating ? (
            <div className="rounded-md border border-hair-soft">
              <RuleBuilder
                projectId={projectId}
                saving={m.create.isPending}
                onCancel={() => setCreating(false)}
                onSave={create}
              />
            </div>
          ) : (
            <Button size="sm" variant="ghost" className="justify-start" onClick={() => setCreating(true)}>
              <Icon icon={Plus} /> New rule
            </Button>
          )
        ) : null}
      </div>
    </Dialog>
  );
}
