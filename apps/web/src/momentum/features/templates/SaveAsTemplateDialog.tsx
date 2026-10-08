import { useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { useSaveProjectTemplate } from './queries';

/** S4.3.1: "Save as template" (project ⋯ menu, admin-only). Captures the project's sections,
 * tasks, subtasks, fields and rules — dates relative to the project's own earliest date,
 * assignees replaced by roles — so it can be replayed into a brand new project later. */
export function SaveAsTemplateDialog({
  projectId,
  open,
  onOpenChange,
  returnFocus,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Where focus goes on close (opened from a menu: the menu's button, H66). */
  returnFocus?: { current: HTMLElement | null };
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const save = useSaveProjectTemplate();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    save.mutate(
      { project_id: projectId, name: name.trim(), description: description.trim() || null },
      {
        onSuccess: () => {
          toast('Template saved');
          onOpenChange(false);
          setName('');
          setDescription('');
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Save as template" returnFocus={returnFocus}>
      <form onSubmit={submit} className="flex flex-col gap-3 p-5">
        <p className="text-sm text-muted">
          Sections, tasks, subtasks, fields and rules are captured; dates become relative to the project's
          earliest one, and assignees become roles you map to people later.
        </p>
        <Input
          aria-label="Template name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Template name"
          maxLength={200}
        />
        <textarea
          aria-label="Template description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (optional)"
          rows={2}
          maxLength={2000}
          className="w-full rounded-md border border-hairline bg-surface-2 px-2.5 py-1.5 text-sm placeholder:text-muted-2 focus:border-focus focus:outline-none"
        />
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!name.trim()}>
            Save template
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
