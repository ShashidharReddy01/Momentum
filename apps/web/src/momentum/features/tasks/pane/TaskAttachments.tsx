import { Download, Paperclip, Trash2, Upload } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';
import { IconButton } from '@/components/ui/IconButton';
import { Icon } from '@/components/ui/Icon';
import { useAttachmentMutations, useTaskAttachments, type Attachment } from '@/features/attachments';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentRow({
  att,
  canEdit,
  onRemove,
}: {
  att: Attachment;
  canEdit: boolean;
  onRemove: () => void;
}) {
  const { api_base } = useMomentumConfig();
  const href = `${api_base}/attachments/${att.id}/download`;
  return (
    <li className="flex h-8 items-center gap-2 text-sm">
      <Icon icon={Paperclip} size={13} className="shrink-0 text-muted" />
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="min-w-0 flex-1 truncate hover:underline"
      >
        {att.filename}
      </a>
      <span className="shrink-0 text-xs text-muted-2">{formatSize(att.size_bytes)}</span>
      <a href={href} target="_blank" rel="noopener noreferrer" aria-label={`Download ${att.filename}`}>
        <IconButton icon={Download} label={`Download ${att.filename}`} size="icon-sm" />
      </a>
      {canEdit ? (
        <IconButton icon={Trash2} label={`Remove ${att.filename}`} size="icon-sm" onClick={onRemove} />
      ) : null}
    </li>
  );
}

/** S2.6.1: a task's files — list, download (visibility-gated on the backend), remove, and
 * attach via a file picker or drag-and-drop onto this section. Paste-to-upload in the comment
 * editor isn't wired up this slice (see STATUS.md) — this pane section is the one shipped
 * upload path. */
export function TaskAttachments({ taskId, canEdit }: { taskId: string; canEdit: boolean }) {
  const list = useTaskAttachments(taskId);
  const m = useAttachmentMutations(taskId);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const files = list.data ?? [];

  const upload = (fileList: FileList | null) => {
    if (!fileList) return;
    for (const file of Array.from(fileList)) m.upload.mutate(file);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (canEdit) upload(e.dataTransfer.files);
  };

  if (!files.length && !canEdit) return null;

  return (
    <section className="mt-6">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="section-label">Files</h3>
        {canEdit ? (
          <>
            <IconButton
              icon={Upload}
              label="Attach a file"
              size="icon-sm"
              onClick={() => inputRef.current?.click()}
            />
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                upload(e.target.files);
                e.target.value = '';
              }}
            />
          </>
        ) : null}
      </div>
      <div
        onDragOver={
          canEdit
            ? (e) => {
                e.preventDefault();
                setDragOver(true);
              }
            : undefined
        }
        onDragLeave={canEdit ? () => setDragOver(false) : undefined}
        onDrop={canEdit ? onDrop : undefined}
        className={cn(
          'rounded-md',
          canEdit && dragOver && 'ring-2 ring-accent ring-offset-1 ring-offset-surface',
        )}
      >
        {files.length ? (
          <ul className="flex flex-col gap-0.5">
            {files.map((a) => (
              <AttachmentRow key={a.id} att={a} canEdit={canEdit} onRemove={() => m.remove.mutate(a.id)} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">
            {canEdit ? 'No files yet — drop one here, or click the upload icon' : 'No files'}
          </p>
        )}
      </div>
    </section>
  );
}
