import { MoreHorizontal, Trash2 } from 'lucide-react';
import { memo, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { CompleteCheck } from '@/components/common/CompleteCheck';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { cn } from '@/lib/cn';
import { isTemp, type Task } from './queries';

export interface TaskRowProps {
  task: Task;
  canEdit: boolean;
  fading?: boolean;
  onToggle: (task: Task) => void;
  onRename: (task: Task, title: string) => void;
  onEnter: (task: Task) => void;
  onDelete: (task: Task) => void;
}

export const TaskRow = memo(function TaskRow({
  task,
  canEdit,
  fading,
  onToggle,
  onRename,
  onEnter,
  onDelete,
}: TaskRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(task.title);
  const input = useRef<HTMLInputElement>(null);
  const done = !!task.completed_at;

  useEffect(() => {
    if (!editing) setDraft(task.title);
  }, [task.title, editing]);
  useEffect(() => {
    if (editing) input.current?.focus();
  }, [editing]);

  const commit = () => {
    setEditing(false);
    const title = draft.trim().replace(/\s+/g, ' ');
    if (title && title !== task.title) onRename(task, title);
    else setDraft(task.title);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
      onEnter(task);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setDraft(task.title);
      setEditing(false);
    }
  };

  return (
    <div
      role="listitem"
      aria-label={task.title}
      data-task-id={task.id}
      className={cn(
        'group/row flex h-9 items-center gap-2.5 border-b border-hair-soft px-2 transition-opacity duration-300 hover:bg-surface-2',
        (done || fading) && 'text-muted',
        fading && 'opacity-60',
      )}
    >
      <CompleteCheck
        checked={done}
        disabled={!canEdit}
        label={done ? `Mark ${task.title} incomplete` : `Complete ${task.title}`}
        onChange={() => onToggle(task)}
      />
      {editing ? (
        <input
          ref={input}
          aria-label="Task name"
          value={draft}
          maxLength={500}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={onKey}
          className="h-7 min-w-0 flex-1 rounded-sm border border-focus bg-surface px-1 text-[13.5px] outline-none"
        />
      ) : (
        <button
          type="button"
          disabled={!canEdit}
          onClick={() => setEditing(true)}
          className={cn(
            'min-w-0 flex-1 cursor-text truncate text-left text-[13.5px] disabled:cursor-default',
            done && 'line-through decoration-muted-2',
          )}
        >
          {task.title}
        </button>
      )}
      <span className="font-mono text-[11px] text-muted-2 opacity-0 group-hover/row:opacity-100">
        {isTemp(task.id) ? '…' : task.key}
      </span>
      {canEdit ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton
              icon={MoreHorizontal}
              label={`Actions for ${task.title}`}
              size="icon-sm"
              className="opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem className="text-crit" onSelect={() => onDelete(task)}>
              <Icon icon={Trash2} /> Delete task
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <span className="w-7" />
      )}
    </div>
  );
});

export function DraftRow({
  onSubmit,
  onPasteLines,
  onCancel,
}: {
  onSubmit: (title: string) => void;
  onPasteLines: (lines: string[]) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState('');
  return (
    <div
      role="listitem"
      aria-label="New task"
      className="flex h-9 items-center gap-2.5 border-b border-hair-soft px-2"
    >
      <CompleteCheck checked={false} disabled label="New task" onChange={() => {}} />
      <input
        aria-label="New task name"
        placeholder="Write a task name"
        value={value}
        maxLength={500}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the user just asked for a new task row
        autoFocus
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          if (value.trim()) onSubmit(value.trim());
          onCancel();
        }}
        onPaste={(e) => {
          const lines = e.clipboardData
            .getData('text')
            .split(/\r?\n/)
            .map((l) => l.trim())
            .filter(Boolean);
          if (lines.length > 1) {
            e.preventDefault();
            onPasteLines(lines);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            const title = value.trim();
            if (!title) return onCancel();
            setValue('');
            onSubmit(title);
          } else if (e.key === 'Escape') {
            e.preventDefault();
            onCancel();
          }
        }}
        className="h-7 min-w-0 flex-1 rounded-sm bg-transparent px-1 text-[13.5px] outline-none placeholder:text-muted-2"
      />
    </div>
  );
}
