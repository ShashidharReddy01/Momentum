import { Copy, MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useHref } from 'react-router';
import { toast } from 'sonner';
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
import { FormBuilder } from './FormBuilder';
import { useFormMutations, useForms, type FormOut, type FormSpec } from './queries';

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`${what} copied`);
  } catch {
    toast(text);
  }
}

function FormRow({
  form,
  canEdit,
  editing,
  onEdit,
  onCloseEdit,
}: {
  form: FormOut;
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
  onCloseEdit: () => void;
}) {
  const m = useFormMutations(form.project_id);
  const publicHref = useHref(`/f/${form.public_token}`);
  const internalHref = useHref(`/projects/${form.project_id}/forms/${form.id}`);

  if (editing) {
    return (
      <li className="rounded-md border border-hair-soft">
        <FormBuilder
          projectId={form.project_id}
          initial={form}
          saving={m.update.isPending}
          onCancel={onCloseEdit}
          onSave={(spec) =>
            m.update.mutate(
              { id: form.id, patch: { ...spec, expected_version: form.version } },
              { onSuccess: onCloseEdit },
            )
          }
        />
      </li>
    );
  }

  return (
    <li className="rounded-md border border-hair-soft p-2.5">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{form.name}</span>
        {!form.enabled ? (
          <span className="rounded bg-hair-soft px-1.5 py-0.5 text-xs text-muted">Off</span>
        ) : null}
        {form.public_enabled ? (
          <span className="rounded bg-accent-2 px-1.5 py-0.5 text-xs text-accent-ink">Public</span>
        ) : null}
        {canEdit ? (
          <>
            <Button size="sm" variant="ghost" onClick={onEdit}>
              Edit
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton icon={MoreHorizontal} label={`${form.name} actions`} size="icon-sm" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={() =>
                    copy(new URL(internalHref, window.location.origin).toString(), 'Internal link')
                  }
                >
                  <Icon icon={Copy} /> Copy internal link
                </DropdownMenuItem>
                {form.public_enabled ? (
                  <DropdownMenuItem
                    onSelect={() =>
                      copy(new URL(publicHref, window.location.origin).toString(), 'Public link')
                    }
                  >
                    <Icon icon={Copy} /> Copy public link
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem className="text-crit" onSelect={() => m.remove.mutate(form.id)}>
                  <Icon icon={Trash2} /> Delete form
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-muted">{form.questions.length} questions</p>
    </li>
  );
}

/** Project "Forms" (⋯ → Forms, S4.2.1): list with an inline builder for creating and editing
 * forms, and links to the internal (logged-in) and public submission pages. Mirrors
 * `RulesDialog`'s shape. */
export function FormsDialog({
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
  const forms = useForms(projectId, open);
  const m = useFormMutations(projectId);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const create = (spec: FormSpec) => m.create.mutate(spec, { onSuccess: () => setCreating(false) });

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Forms" className="w-[min(640px,calc(100vw-32px))]">
      <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto p-5">
        {forms.isPending ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : (
          <ul aria-label="Forms on this project" className="flex flex-col gap-2">
            {(forms.data ?? []).map((f) => (
              <FormRow
                key={f.id}
                form={f}
                canEdit={canEdit}
                editing={editingId === f.id}
                onEdit={() => setEditingId(f.id)}
                onCloseEdit={() => setEditingId(null)}
              />
            ))}
            {forms.data?.length === 0 && !creating ? (
              <p className="px-1 py-1 text-sm text-muted">No forms on this project yet.</p>
            ) : null}
          </ul>
        )}

        {canEdit ? (
          creating ? (
            <div className="rounded-md border border-hair-soft">
              <FormBuilder
                projectId={projectId}
                saving={m.create.isPending}
                onCancel={() => setCreating(false)}
                onSave={create}
              />
            </div>
          ) : (
            <Button size="sm" variant="ghost" className="justify-start" onClick={() => setCreating(true)}>
              <Icon icon={Plus} /> New form
            </Button>
          )
        ) : null}
      </div>
    </Dialog>
  );
}
