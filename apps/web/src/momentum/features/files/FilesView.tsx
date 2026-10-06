import {
  Archive,
  Download,
  File as FileIcon,
  FileImage,
  FileSpreadsheet,
  FileText,
  FolderUp,
  History,
  Mail,
  MoreHorizontal,
  Presentation,
  Search,
  SquareArrowOutUpRight,
  Trash2,
  Upload,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { FILE_DRAG_TYPE } from '@/features/ai';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { useTaskNav } from '@/features/tasks';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';
import { formatDay } from '@/lib/dates';
import { useUi } from '@/stores/ui';
import {
  useFileMutations,
  useFileVersions,
  useProjectFiles,
  type FileFilters,
  type FileKind,
  type ProjectFile,
} from './queries';

const KIND_ICON: Record<FileKind, LucideIcon> = {
  document: FileText,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  pdf: FileText,
  image: FileImage,
  text: FileText,
  email: Mail,
  archive: Archive,
  other: FileIcon,
};
const KIND_LABEL: Record<FileKind, string> = {
  document: 'Documents',
  spreadsheet: 'Spreadsheets',
  presentation: 'Presentations',
  pdf: 'PDFs',
  image: 'Images',
  text: 'Text',
  email: 'Emails',
  archive: 'Archives',
  other: 'Other',
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const selectClass =
  'h-8 rounded-md border border-hairline bg-surface px-2 text-sm shadow-raise hover:border-muted-2/60 focus:border-focus focus:outline-none focus:ring-2 focus:ring-focus/25';

/** Phase 7.5 (spec §3.3): the project's Files tab. Every file the viewer can see in the project
 * (its own uploads, tasks at any depth, comments), one row per file (its current version). */
export function FilesView({
  projectId,
  canEdit,
  isAdmin,
}: {
  projectId: string;
  canEdit: boolean;
  isAdmin: boolean;
}) {
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [filters, setFilters] = useState<FileFilters>({ where: 'all', sort: 'newest' });
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const all = useMemo(() => ({ ...filters, q: debounced || undefined }), [filters, debounced]);
  const list = useProjectFiles(projectId, all);
  const m = useFileMutations(projectId);
  const people = usePeople('');
  const me = useMe();
  const inputRef = useRef<HTMLInputElement>(null);
  const versionInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<ProjectFile | null>(null);
  const [versionsOf, setVersionsOf] = useState<ProjectFile | null>(null);
  const [versionTarget, setVersionTarget] = useState<ProjectFile | null>(null);
  const [pending, setPending] = useState<{ file: File; match: ProjectFile }[]>([]);
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.data) ?? [], [list.data]);
  const total = list.data?.pages[0]?.total ?? 0;

  /** Same name as a current file uploaded to the project itself → ask before adding a copy. */
  const upload = (files: FileList | File[] | null) => {
    if (!files || !canEdit) return;
    const asks: { file: File; match: ProjectFile }[] = [];
    for (const file of Array.from(files)) {
      const match = rows.find(
        (r) => r.location.type === 'project' && r.filename.toLowerCase() === file.name.toLowerCase(),
      );
      if (match) asks.push({ file, match });
      else m.upload.mutate({ file });
    }
    if (asks.length) setPending((p) => [...p, ...asks]);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    upload(e.dataTransfer.files);
  };
  const filtered = !!(
    debounced ||
    filters.kind ||
    filters.source ||
    filters.uploaded_by ||
    filters.where !== 'all'
  );

  return (
    <div
      className={cn('relative flex min-h-full flex-col gap-3 rounded-lg', dragOver && 'ring-2 ring-accent')}
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
    >
      <div role="toolbar" aria-label="Files" className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Icon icon={Search} size={14} className="pointer-events-none absolute left-2 top-2 text-muted-2" />
          <Input
            aria-label="Search files"
            placeholder="Search names and text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="pl-7"
          />
        </div>
        <select
          aria-label="Kind"
          className={selectClass}
          value={filters.kind ?? ''}
          onChange={(e) =>
            setFilters((f) => ({ ...f, kind: (e.target.value || undefined) as FileKind | undefined }))
          }
        >
          <option value="">All kinds</option>
          {(Object.keys(KIND_LABEL) as FileKind[]).map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <select
          aria-label="Where"
          className={selectClass}
          value={filters.where ?? 'all'}
          onChange={(e) => setFilters((f) => ({ ...f, where: e.target.value as FileFilters['where'] }))}
        >
          <option value="all">Anywhere</option>
          <option value="project">Uploaded to the project</option>
          <option value="tasks">On tasks</option>
          <option value="comments">On comments</option>
        </select>
        <select
          aria-label="Source"
          className={selectClass}
          value={filters.source ?? ''}
          onChange={(e) =>
            setFilters((f) => ({ ...f, source: (e.target.value || undefined) as FileFilters['source'] }))
          }
        >
          <option value="">Any source</option>
          <option value="upload">Uploads</option>
          <option value="generated">Reports</option>
          <option value="agent">From agents</option>
          <option value="import">Imported</option>
        </select>
        <select
          aria-label="Uploaded by"
          className={selectClass}
          value={filters.uploaded_by ?? ''}
          onChange={(e) => setFilters((f) => ({ ...f, uploaded_by: e.target.value || undefined }))}
        >
          <option value="">Anyone</option>
          {(people.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Sort"
          className={selectClass}
          value={filters.sort ?? 'newest'}
          onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value as FileFilters['sort'] }))}
        >
          <option value="newest">Newest first</option>
          <option value="name">Name</option>
          <option value="size">Largest first</option>
        </select>
        {canEdit ? (
          <>
            <Button size="sm" className="ml-auto" onClick={() => inputRef.current?.click()}>
              <Icon icon={Upload} /> Upload
            </Button>
            <input
              ref={inputRef}
              type="file"
              multiple
              hidden
              data-testid="files-upload-input"
              onChange={(e) => {
                upload(e.target.files);
                e.target.value = '';
              }}
            />
          </>
        ) : null}
        <input
          ref={versionInputRef}
          type="file"
          hidden
          data-testid="files-version-input"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file && versionTarget) m.uploadVersion.mutate({ file, target: versionTarget });
            setVersionTarget(null);
            e.target.value = '';
          }}
        />
      </div>

      {list.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : rows.length === 0 ? (
        filtered ? (
          <EmptyState icon={Search} title="No files match">
            Try another search or clear the filters.
          </EmptyState>
        ) : (
          <EmptyState icon={FolderUp} title="No files yet">
            Files attached to tasks and comments show up here too.
            {canEdit ? ' Drop files here or use Upload.' : ''}
          </EmptyState>
        )
      ) : (
        <div className="flex min-h-0 gap-4">
          <div className="min-w-0 flex-1">
            <FilesGrid
              rows={rows}
              total={total}
              onPreview={setPreview}
              actions={(f) => (
                <RowMenu
                  file={f}
                  projectId={projectId}
                  canEdit={canEdit}
                  canDelete={isAdmin || f.uploaded_by === me.data?.user.id}
                  onPreview={() => setPreview(f)}
                  onVersions={() => setVersionsOf(f)}
                  onNewVersion={() => {
                    setVersionTarget(f);
                    versionInputRef.current?.click();
                  }}
                  onDelete={() => m.remove.mutate(f)}
                />
              )}
            />
            {list.hasNextPage ? (
              <div className="mt-3 flex justify-center">
                <Button
                  size="sm"
                  variant="ghost"
                  loading={list.isFetchingNextPage}
                  onClick={() => void list.fetchNextPage()}
                >
                  Show more ({rows.length} of {total})
                </Button>
              </div>
            ) : null}
          </div>
          {preview ? (
            <PreviewPanel file={preview} projectId={projectId} onClose={() => setPreview(null)} />
          ) : null}
          {versionsOf ? <VersionsPanel file={versionsOf} onClose={() => setVersionsOf(null)} /> : null}
        </div>
      )}

      {pending[0] ? (
        <Dialog
          open
          onOpenChange={(o) => !o && setPending((p) => p.slice(1))}
          title={`Upload as a new version of ${pending[0].match.filename}?`}
          description={`A file with this name is already in the project (v${pending[0].match.version}).`}
        >
          <div className="flex justify-end gap-2 px-5 py-4">
            <Button
              variant="ghost"
              onClick={() => {
                m.upload.mutate({ file: pending[0]!.file });
                setPending((p) => p.slice(1));
              }}
            >
              Keep both
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                m.upload.mutate({ file: pending[0]!.file, replaceId: pending[0]!.match.id });
                setPending((p) => p.slice(1));
              }}
            >
              New version
            </Button>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}

const COLUMNS = ['Name', 'Where', 'Uploaded by', 'Date', 'Size', ''];

/** A `role="grid"` table with roving focus (design-system grid pattern): ↑/↓ move between rows,
 * Home/End jump, Enter opens the preview; Tab leaves the grid. */
function FilesGrid({
  rows,
  total,
  onPreview,
  actions,
}: {
  rows: ProjectFile[];
  total: number;
  onPreview: (f: ProjectFile) => void;
  actions: (f: ProjectFile) => React.ReactNode;
}) {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const nav = useTaskNav();
  const focus = (i: number) => {
    const next = Math.max(0, Math.min(rows.length - 1, i));
    setActive(next);
    refs.current[next]?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>, i: number) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'ArrowDown') focus(i + 1);
    else if (e.key === 'ArrowUp') focus(i - 1);
    else if (e.key === 'Home') focus(0);
    else if (e.key === 'End') focus(rows.length - 1);
    else if (e.key === 'Enter' || e.key === ' ') onPreview(rows[i]!);
    else return;
    e.preventDefault();
  };
  return (
    <div
      role="grid"
      aria-label="Project files"
      aria-rowcount={total + 1}
      className="w-full overflow-x-auto rounded-xl border border-hair-soft bg-surface"
    >
      <div
        role="row"
        className="grid grid-cols-[minmax(0,2.4fr)_minmax(0,1.6fr)_minmax(0,1fr)_88px_72px_40px] border-b border-hair-soft px-3 py-2 text-xs text-muted max-md:hidden"
      >
        {COLUMNS.map((c, i) => (
          <div key={i} role="columnheader">
            {c ? c : <span className="sr-only">Actions</span>}
          </div>
        ))}
      </div>
      {rows.map((f, i) => (
        <div
          key={f.id}
          role="row"
          aria-rowindex={i + 2}
          tabIndex={i === active ? 0 : -1}
          ref={(el) => {
            refs.current[i] = el;
          }}
          onFocus={() => setActive(i)}
          onKeyDown={(e) => onKey(e, i)}
          onDoubleClick={() => onPreview(f)}
          // drag a row into Ask Mo's composer to ask about it (Phase 7.5)
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData(FILE_DRAG_TYPE, JSON.stringify({ id: f.id, name: f.filename }));
            e.dataTransfer.effectAllowed = 'copy';
          }}
          className="grid grid-cols-[minmax(0,2.4fr)_minmax(0,1.6fr)_minmax(0,1fr)_88px_72px_40px] items-center gap-x-2 border-b border-hair-soft px-3 py-1.5 text-sm last:border-b-0 hover:bg-surface-2 focus:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus max-md:grid-cols-[minmax(0,1fr)_40px]"
        >
          <div role="gridcell" className="flex min-w-0 items-center gap-2">
            <Icon icon={KIND_ICON[f.kind]} size={15} className="shrink-0 text-muted" />
            <button
              type="button"
              tabIndex={-1}
              className="min-w-0 truncate text-left hover:underline"
              onClick={() => onPreview(f)}
              title={f.filename}
            >
              {f.filename}
            </button>
            {f.version > 1 ? (
              <span
                className="shrink-0 rounded border border-hair-soft px-1 font-mono text-[11px] text-muted"
                title={`${f.versions_count} versions`}
              >
                v{f.version}
              </span>
            ) : null}
            {f.source === 'generated' ? (
              <span className="shrink-0 rounded border border-hair-soft px-1 text-[11px] text-muted">
                Report
              </span>
            ) : null}
            {f.ai_drafted ? (
              <span
                className="shrink-0 rounded border border-amber/50 px-1 text-[11px] text-amber-ink"
                title="Contains AI-drafted text: review before sending"
              >
                AI-drafted
              </span>
            ) : null}
          </div>
          <div role="gridcell" className="min-w-0 truncate text-muted max-md:hidden">
            {f.location.type === 'project' ? (
              'Project'
            ) : f.location.task_id ? (
              <button
                type="button"
                tabIndex={-1}
                className="min-w-0 truncate hover:underline"
                onClick={() => nav?.open(f.location.task_id!)}
              >
                <span className="font-mono text-xs">{f.location.task_key}</span> {f.location.task_title}
                {f.location.type === 'comment' ? ' (comment)' : ''}
              </button>
            ) : (
              '—'
            )}
          </div>
          <div role="gridcell" className="truncate text-muted max-md:hidden">
            {f.uploaded_by_name}
          </div>
          <div role="gridcell" className="text-muted max-md:hidden">
            {formatDay(f.created_at.slice(0, 10))}
          </div>
          <div role="gridcell" className="text-muted max-md:hidden">
            {formatSize(f.size_bytes)}
          </div>
          <div role="gridcell" className="flex justify-end">
            {actions(f)}
          </div>
        </div>
      ))}
    </div>
  );
}

function RowMenu({
  file,
  projectId,
  canEdit,
  canDelete,
  onPreview,
  onVersions,
  onNewVersion,
  onDelete,
}: {
  file: ProjectFile;
  projectId: string;
  canEdit: boolean;
  canDelete: boolean;
  onPreview: () => void;
  onVersions: () => void;
  onNewVersion: () => void;
  onDelete: () => void;
}) {
  const { api_base, ai_enabled } = useMomentumConfig();
  const nav = useTaskNav();
  const askAbout = useUi((s) => s.askAbout);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <IconButton
          icon={MoreHorizontal}
          label={`Actions for ${file.filename}`}
          size="icon-sm"
          tabIndex={-1}
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={onPreview}>
          <Icon icon={FileText} /> Preview
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => {
            window.location.href = `${api_base}/attachments/${file.id}/download`;
          }}
        >
          <Icon icon={Download} /> Download
        </DropdownMenuItem>
        {file.location.task_id ? (
          <DropdownMenuItem onSelect={() => nav?.open(file.location.task_id!)}>
            <Icon icon={SquareArrowOutUpRight} /> Open its task
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem onSelect={onVersions}>
          <Icon icon={History} /> Versions{file.versions_count > 1 ? ` (${file.versions_count})` : ''}
        </DropdownMenuItem>
        {canEdit ? (
          <DropdownMenuItem onSelect={onNewVersion}>
            <Icon icon={Upload} /> Upload new version
          </DropdownMenuItem>
        ) : null}
        {ai_enabled ? (
          <DropdownMenuItem
            onSelect={() => askAbout({ kind: 'file', fileId: file.id, label: file.filename, projectId })}
          >
            <MoMark size={13} /> Ask Mo about this file
          </DropdownMenuItem>
        ) : null}
        {canDelete ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-crit" onSelect={onDelete}>
              <Icon icon={Trash2} /> Delete
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SidePanel({
  label,
  title,
  onClose,
  children,
}: {
  label: string;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <aside
      aria-label={label}
      className="flex shrink-0 flex-col rounded-xl border border-hair-soft bg-surface max-md:fixed max-md:inset-x-2 max-md:bottom-2 max-md:z-30 max-md:max-h-[70vh] max-md:shadow-pop md:sticky md:top-0 md:max-h-[calc(100vh-var(--topbar-h)-140px)] md:w-[min(380px,38vw)]"
    >
      <header className="flex items-start gap-2 border-b border-hair-soft px-4 py-3">
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold" title={title}>
          {title}
        </h2>
        <IconButton icon={X} label="Close" size="icon-sm" onClick={onClose} />
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
    </aside>
  );
}

function TextPreview({ url }: { url: string }) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    fetch(url, { credentials: 'include' })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((t) => live && setText(t.slice(0, 20000)))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [url]);
  if (failed) return <p className="text-sm text-muted">We couldn&apos;t load a preview.</p>;
  if (text === null) return <Skeleton className="h-40" />;
  // plain text only: markdown and HTML are shown as their source, never rendered
  return <pre className="whitespace-pre-wrap break-words font-mono text-xs text-ink-2">{text}</pre>;
}

/** Spec §3.3: images inline, PDFs in a sandboxed frame, text as plain text, the rest as details. */
function PreviewPanel({
  file,
  projectId,
  onClose,
}: {
  file: ProjectFile;
  projectId: string;
  onClose: () => void;
}) {
  const { api_base, ai_enabled } = useMomentumConfig();
  const askAbout = useUi((s) => s.askAbout);
  const url = `${api_base}/attachments/${file.id}/download`;
  const imageOk = file.kind === 'image' && /^image\/(png|jpeg|gif|webp|avif)$/.test(file.mime);
  return (
    <SidePanel label="File preview" title={file.filename} onClose={onClose}>
      {imageOk ? (
        <img src={url} alt={file.filename} className="max-h-[50vh] w-full rounded-md object-contain" />
      ) : file.kind === 'pdf' && file.mime === 'application/pdf' ? (
        <iframe
          title={`Preview of ${file.filename}`}
          src={url}
          sandbox=""
          className="h-[50vh] w-full rounded-md border border-hair-soft"
        />
      ) : file.kind === 'text' || file.mime.startsWith('text/') ? (
        <TextPreview url={url} />
      ) : (
        <p className="text-sm text-muted">No preview for this kind of file.</p>
      )}
      <dl className="mt-4 grid grid-cols-[96px_1fr] gap-y-1 text-sm">
        <dt className="text-muted">Size</dt>
        <dd>{formatSize(file.size_bytes)}</dd>
        <dt className="text-muted">Type</dt>
        <dd className="truncate">{file.mime}</dd>
        <dt className="text-muted">Uploaded</dt>
        <dd>
          {formatDay(file.created_at.slice(0, 10))} by {file.uploaded_by_name}
        </dd>
        <dt className="text-muted">Version</dt>
        <dd>
          v{file.version} of {file.versions_count}
        </dd>
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onClick={() => (window.location.href = url)}>
          <Icon icon={Download} /> Download
        </Button>
        {ai_enabled ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => askAbout({ kind: 'file', fileId: file.id, label: file.filename, projectId })}
          >
            <MoMark size={13} /> Ask Mo about this file
          </Button>
        ) : null}
      </div>
    </SidePanel>
  );
}

function VersionsPanel({ file, onClose }: { file: ProjectFile; onClose: () => void }) {
  const { api_base } = useMomentumConfig();
  const versions = useFileVersions(file.id);
  return (
    <SidePanel label="Versions" title={`Versions of ${file.filename}`} onClose={onClose}>
      {versions.isPending ? (
        <Skeleton className="h-24" />
      ) : versions.isError ? (
        <p role="alert" className="text-sm text-muted">
          We couldn&apos;t load the versions.
        </p>
      ) : (
        <ol className="divide-y divide-hair-soft">
          {versions.data.map((v) => (
            <li key={v.id} className="flex items-center gap-2 py-2 text-sm">
              <span className="w-8 font-mono text-xs text-muted">v{v.version}</span>
              <span className="min-w-0 flex-1 truncate">
                {formatDay(v.created_at.slice(0, 10))} · {formatSize(v.size_bytes)}
                {v.is_current ? <span className="ml-2 text-xs text-ok">Current</span> : null}
              </span>
              <a
                href={`${api_base}/attachments/${v.id}/download`}
                className="text-xs text-ink-2 underline-offset-2 hover:underline"
                aria-label={`Download version ${v.version}`}
              >
                Download
              </a>
            </li>
          ))}
        </ol>
      )}
    </SidePanel>
  );
}
