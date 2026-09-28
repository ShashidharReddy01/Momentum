import { MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { useSections } from '@/features/sections';
import {
  useDeleteTemplate,
  useNewTaskFromTemplate,
  useSaveTaskTemplate,
  useTaskTemplates,
  type TemplateOut,
} from './queries';

function NewTaskFromTemplateForm({
  projectId,
  template,
  onDone,
}: {
  projectId: string;
  template: TemplateOut;
  onDone: () => void;
}) {
  const sections = useSections(projectId);
  const [sectionId, setSectionId] = useState('');
  const create = useNewTaskFromTemplate(template.id);

  return (
    <div className="flex items-center gap-1.5 pl-6">
      <select
        aria-label={`Section for a new "${template.name}" task`}
        value={sectionId}
        onChange={(e) => setSectionId(e.target.value)}
        className="h-7 rounded-md border border-hairline bg-surface-2 px-2 text-xs"
      >
        <option value="">Default section</option>
        {(sections.data ?? []).map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      <Button
        size="sm"
        variant="ghost"
        loading={create.isPending}
        onClick={() =>
          create.mutate(
            { section_id: sectionId || null },
            {
              onSuccess: () => {
                toast('Task created');
                onDone();
              },
            },
          )
        }
      >
        Add task
      </Button>
    </div>
  );
}

function TaskTemplateRow({ projectId, template }: { projectId: string; template: TemplateOut }) {
  const [expanded, setExpanded] = useState(false);
  const remove = useDeleteTemplate('task', projectId);

  return (
    <li className="rounded-md border border-hair-soft p-2.5">
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="min-w-0 flex-1 truncate text-left text-sm font-medium"
          onClick={() => setExpanded((v) => !v)}
        >
          {template.name}
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton icon={MoreHorizontal} label={`${template.name} actions`} size="icon-sm" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem className="text-crit" onSelect={() => remove.mutate(template.id)}>
              <Icon icon={Trash2} /> Delete template
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {expanded ? (
        <NewTaskFromTemplateForm
          projectId={projectId}
          template={template}
          onDone={() => setExpanded(false)}
        />
      ) : null}
    </li>
  );
}

function NewTaskTemplateForm({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [subtasksText, setSubtasksText] = useState('');
  const save = useSaveTaskTemplate(projectId);

  const submit = () => {
    if (!name.trim() || !title.trim()) return;
    const subtasks = subtasksText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    save.mutate(
      {
        name: name.trim(),
        title: title.trim(),
        description: description.trim() || null,
        subtasks,
        field_values: {},
      },
      { onSuccess: onDone },
    );
  };

  return (
    <div className="flex flex-col gap-2 rounded-md border border-hair-soft p-3">
      <Input
        aria-label="Template name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Template name (e.g. Bug report)"
        maxLength={200}
      />
      <Input
        aria-label="Default task title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Default task title"
        maxLength={200}
      />
      <textarea
        aria-label="Default description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Default description (optional)"
        rows={2}
        maxLength={2000}
        className="w-full rounded-md border border-hairline bg-surface-2 px-2.5 py-1.5 text-sm placeholder:text-muted-2 focus:border-focus focus:outline-none"
      />
      <textarea
        aria-label="Subtask checklist, one per line"
        value={subtasksText}
        onChange={(e) => setSubtasksText(e.target.value)}
        placeholder={'Subtasks, one per line (optional)\nReproduce\nFix\nVerify'}
        rows={3}
        className="w-full rounded-md border border-hairline bg-surface-2 px-2.5 py-1.5 text-sm placeholder:text-muted-2 focus:border-focus focus:outline-none"
      />
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          size="sm"
          variant="primary"
          loading={save.isPending}
          disabled={!name.trim() || !title.trim()}
          onClick={submit}
        >
          Save template
        </Button>
      </div>
    </div>
  );
}

/** S4.3.2: per-project task templates (project ⋯ → Task templates). A template is authored
 * directly here (title, description, a subtask checklist) rather than captured from an existing
 * task; expanding a row lets you create a task from it in a chosen section. */
export function TaskTemplatesDialog({
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
  const templates = useTaskTemplates(projectId, open);
  const [creating, setCreating] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Task templates"
      className="w-[min(520px,calc(100vw-32px))]"
    >
      <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto p-5">
        {templates.isPending ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : (
          <ul aria-label="Task templates" className="flex flex-col gap-2">
            {(templates.data ?? []).map((t) => (
              <TaskTemplateRow key={t.id} projectId={projectId} template={t} />
            ))}
            {templates.data?.length === 0 && !creating ? (
              <p className="px-1 py-1 text-sm text-muted">No task templates on this project yet.</p>
            ) : null}
          </ul>
        )}
        {canEdit ? (
          creating ? (
            <NewTaskTemplateForm projectId={projectId} onDone={() => setCreating(false)} />
          ) : (
            <Button size="sm" variant="ghost" className="justify-start" onClick={() => setCreating(true)}>
              <Icon icon={Plus} /> New task template
            </Button>
          )
        ) : null}
      </div>
    </Dialog>
  );
}
