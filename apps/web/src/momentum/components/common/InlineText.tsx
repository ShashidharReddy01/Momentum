import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { cn } from '@/lib/cn';

export interface InlineTextProps {
  value: string;
  onCommit: (value: string) => void;
  'aria-label': string;
  disabled?: boolean;
  className?: string;
  inputClassName?: string;
  placeholder?: string;
  /** Reject empty values (restores the previous value). */
  required?: boolean;
  multiline?: boolean;
}

/** Click-to-edit text. Enter commits, Escape cancels, blur commits. */
export function InlineText({
  value,
  onCommit,
  disabled,
  className,
  inputClassName,
  placeholder,
  required = true,
  multiline,
  ...aria
}: InlineTextProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);
  useEffect(() => {
    if (editing) ref.current?.select();
  }, [editing]);

  const commit = () => {
    setEditing(false);
    const next = multiline ? draft.trim() : draft.trim().replace(/\s+/g, ' ');
    if ((required && !next) || next === value) {
      setDraft(value);
      return;
    }
    onCommit(next);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && (!multiline || e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      commit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setDraft(value);
      setEditing(false);
    }
  };

  if (disabled) {
    return <span className={className}>{value || <span className="text-muted-2">{placeholder}</span>}</span>;
  }
  if (!editing) {
    return (
      <button
        type="button"
        aria-label={`${aria['aria-label']}: ${value || 'empty'}. Click to edit`}
        onClick={() => setEditing(true)}
        className={cn('max-w-full cursor-text rounded-sm text-left hover:bg-surface-2', className)}
      >
        {value || <span className="text-muted-2">{placeholder}</span>}
      </button>
    );
  }
  const shared = {
    ref,
    value: draft,
    'aria-label': aria['aria-label'],
    placeholder,
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onBlur: commit,
    onKeyDown: onKey,
    className: cn(
      'w-full rounded-sm border border-focus bg-surface px-1 outline-none',
      className,
      inputClassName,
    ),
  };
  return multiline ? <textarea rows={3} {...shared} /> : <input {...shared} />;
}
