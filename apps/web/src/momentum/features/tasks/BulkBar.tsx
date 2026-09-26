import { CalendarDays, CheckCircle2, FolderInput, Trash2, UserRound, X } from 'lucide-react';
import { AskMoButton } from '@/components/common/AI';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import type { DueValue } from '@/lib/dates';
import type { MoContext } from '@/stores/ui';
import { AssigneePicker } from './AssigneePicker';
import { DatePicker } from './DatePicker';

export type BulkPicker = 'assignee' | 'due' | null;

/** Floating bar for the selected tasks: assign, due, move to section, complete, delete. */
export function BulkBar({
  count,
  sections,
  picker,
  onPickerChange,
  onAssign,
  onDue,
  onMove,
  onComplete,
  onDelete,
  onClear,
  askAbout,
}: {
  count: number;
  sections: { id: string; name: string }[];
  picker: BulkPicker;
  onPickerChange: (p: BulkPicker) => void;
  onAssign: (user: { id: string; name: string } | null) => void;
  onDue: (value: DueValue | null) => void;
  onMove: (sectionId: string) => void;
  onComplete: () => void;
  onDelete: () => void;
  onClear: () => void;
  /** "Ask Mo about these tasks" (S3.3.2); hidden while AI is off. */
  askAbout?: Omit<MoContext, 'id'>;
}) {
  return (
    <div
      role="toolbar"
      aria-label={`${count} tasks selected`}
      className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-1 rounded-xl bg-surface p-1.5 pl-3 shadow-pop"
    >
      <span className="tabular mr-2 text-sm font-medium">{count} selected</span>
      <AssigneePicker
        open={picker === 'assignee'}
        onOpenChange={(o) => onPickerChange(o ? 'assignee' : null)}
        assigneeId={null}
        allowClear
        onChange={onAssign}
      >
        <Button size="sm" variant="ghost">
          <Icon icon={UserRound} /> Assign
        </Button>
      </AssigneePicker>
      <DatePicker
        open={picker === 'due'}
        onOpenChange={(o) => onPickerChange(o ? 'due' : null)}
        dueOn={null}
        dueAt={null}
        allowClear
        onChange={onDue}
      >
        <Button size="sm" variant="ghost">
          <Icon icon={CalendarDays} /> Due date
        </Button>
      </DatePicker>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="ghost">
            <Icon icon={FolderInput} /> Move
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="center">
          {sections.map((s) => (
            <DropdownMenuItem key={s.id} onSelect={() => onMove(s.id)}>
              {s.name}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <Button size="sm" variant="ghost" onClick={onComplete}>
        <Icon icon={CheckCircle2} /> Complete
      </Button>
      <Button size="sm" variant="ghost" className="text-crit" onClick={onDelete}>
        <Icon icon={Trash2} /> Delete
      </Button>
      <span className="mx-1 h-5 w-px bg-hairline" />
      {askAbout ? <AskMoButton about={askAbout} /> : null}
      <IconButton icon={X} label="Clear selection" shortcut="Esc" size="icon-sm" onClick={onClear} />
    </div>
  );
}
