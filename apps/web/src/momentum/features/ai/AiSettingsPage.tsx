import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { InlineText } from '@/components/common/InlineText';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { AdminAiSection } from './AdminAiSection';
import { useAiPrefs, useMemoryMutations, useWorkspaceMemory } from './memoryQueries';

const MAX = 300;

/**
 * `/settings/ai` (S3.1.5): workspace memory — short facts Mo carries into every conversation
 * ("Sprints start on Mondays"). Everyone can read them (they shape everyone's answers); only a
 * workspace admin can change them (the API enforces that too). S3.5.2 adds an admin-only section
 * (`AdminAiSection`) below it: enable/disable, budget, auto-apply policy, model aliases and usage.
 */
export function AiSettingsPage() {
  const me = useMe();
  const isAdmin = me.data?.user.role === 'admin';
  const memory = useWorkspaceMemory();
  const m = useMemoryMutations();
  const [draft, setDraft] = useState('');
  const { prefs, save } = useAiPrefs();

  const add = () => {
    const text = draft.trim();
    if (!text) return;
    m.create.mutate(text, { onSuccess: () => setDraft('') });
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 md:px-8">
      <h1 className="page-title">AI settings</h1>
      <section aria-labelledby="mine-title" className="mt-6">
        <h2 id="mine-title" className="text-[15px] font-semibold">
          For you
        </h2>
        <label className="mt-3 flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={prefs?.auto_apply_low_risk ?? false}
            disabled={!prefs || save.isPending}
            onChange={(e) => save.mutate({ auto_apply_low_risk: e.target.checked })}
          />
          <span>
            Apply low-risk changes from Mo without asking
            <span className="block text-muted">
              Small edits you ask for in ⌘K (a due date, an assignee, a completion) go through right away,
              with Undo. Bigger or risky changes always show a preview first.
            </span>
          </span>
        </label>
      </section>
      <section aria-labelledby="memory-title" className="mt-6">
        <h2 id="memory-title" className="flex items-center gap-1.5 text-[15px] font-semibold">
          <MoMark size={14} /> Workspace memory
        </h2>
        <p className="mt-1 text-sm text-muted">
          Facts Mo should always know about how this team works. Keep each one short.
          {isAdmin ? '' : ' Only workspace admins can change them.'}
        </p>
        {memory.isPending ? (
          <div className="mt-4 flex flex-col gap-2">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : memory.data?.length ? (
          <ul aria-label="Memory" className="mt-4 flex flex-col divide-y divide-hair-soft">
            {memory.data.map((b) => (
              <li key={b.id} className="flex items-center gap-2 py-2">
                <span aria-hidden className="text-muted">
                  •
                </span>
                {isAdmin ? (
                  <InlineText
                    value={b.text}
                    aria-label="Memory bullet"
                    className="min-w-0 flex-1 text-sm"
                    onCommit={(text) => m.update.mutate({ id: b.id, text })}
                  />
                ) : (
                  <span className="min-w-0 flex-1 text-sm">{b.text}</span>
                )}
                {isAdmin ? (
                  <IconButton
                    icon={Trash2}
                    label={`Remove "${b.text}"`}
                    size="icon-sm"
                    onClick={() => m.remove.mutate(b.id)}
                  />
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-4">
            <EmptyState title="No workspace memory yet">
              {isAdmin
                ? 'Add facts like team rituals, naming conventions or who owns what.'
                : 'An admin can add some.'}
            </EmptyState>
          </div>
        )}
        {isAdmin ? (
          <form
            className="mt-4 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              add();
            }}
          >
            <Input
              aria-label="New memory bullet"
              placeholder="e.g. Sprints start on Mondays"
              maxLength={MAX}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="flex-1"
            />
            <Button type="submit" variant="primary" disabled={!draft.trim()} loading={m.create.isPending}>
              Add
            </Button>
          </form>
        ) : null}
      </section>
      {isAdmin ? <AdminAiSection /> : null}
    </div>
  );
}
