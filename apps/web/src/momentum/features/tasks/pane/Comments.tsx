import { Pencil, SmilePlus, Trash2 } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { RichTextView } from '@/components/editor/RichTextView';
import { Avatar } from '@/components/ui/Avatar';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { Skeleton } from '@/components/ui/Skeleton';
import { Segmented } from '@/components/ui/Tabs';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { useSections } from '@/features/sections';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/dates';
import {
  feedKey,
  REACTIONS,
  useCommentMutations,
  useTaskFeed,
  type Comment,
  type FeedItem,
} from '../comments';
import type { TaskDetail } from '../detail';
import { CommentEditor } from './CommentEditor';
import { buildFeed } from './feedText';

type FeedFilter = 'all' | 'comments' | 'activity';
const FILTER_KEY = 'momentum.feedFilter';

/** Comments and activity on a task (oldest first), with the composer at the bottom. */
export function Comments({ task }: { task: TaskDetail }) {
  const qc = useQueryClient();
  const feed = useTaskFeed(task.id);
  const meId = useMe().data?.user.id;
  const people = usePeople().data ?? [];
  const sections = useSections(task.project?.id ?? '', !!task.project).data;
  const nameOf = (id: string | null | undefined) => people.find((p) => p.id === id)?.name;
  const m = useCommentMutations(task.id, meId);
  const canComment = task.my_role === 'admin' || task.my_role === 'editor' || task.my_role === 'commenter';
  const [filter, setFilterState] = useState<FeedFilter>(() => {
    try {
      const v = localStorage.getItem(FILTER_KEY);
      return v === 'comments' || v === 'activity' ? v : 'all';
    } catch {
      return 'all';
    }
  });
  const setFilter = (f: FeedFilter) => {
    setFilterState(f);
    try {
      localStorage.setItem(FILTER_KEY, f);
    } catch {
      /* ignore */
    }
  };
  // Refresh the feed when the task changes (edits from the pane, the list, or subtasks).
  const signature = `${task.version}:${task.subtask_count}:${task.completed_subtask_count}:${(task.followers ?? []).length}`;
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: feedKey(task.id) });
  }, [qc, task.id, signature]);

  const names = {
    person: (id: string) => nameOf(id),
    section: (id: string) => sections?.find((s) => s.id === id)?.name,
  };
  const entries = feed.data ? buildFeed(feed.data.data, names, filter) : [];

  return (
    <section aria-label="Comments and activity" className="mt-8">
      <div className="mb-2 flex items-center gap-3">
        <h3 className="section-label">Activity</h3>
        <Segmented
          label="Show"
          value={filter}
          onChange={(v) => setFilter(v)}
          options={[
            { value: 'all', label: 'All' },
            { value: 'comments', label: 'Comments' },
            { value: 'activity', label: 'Changes' },
          ]}
        />
      </div>
      {feed.isPending ? (
        <Skeleton className="h-12" />
      ) : (
        <ol className="flex flex-col gap-3" aria-label="Feed">
          {feed.data?.truncated ? <li className="text-xs text-muted">Older activity is not shown.</li> : null}
          {entries.map((e) =>
            e.kind === 'comment' ? (
              <CommentItem
                key={e.item.comment!.id}
                comment={e.item.comment!}
                meId={meId}
                authorName={nameOf(e.item.comment!.author_id) ?? 'Former member'}
                nameOf={nameOf}
                canReact={canComment}
                onEdit={async (body) =>
                  !!(await m.edit.mutateAsync({ id: e.item.comment!.id, body }).catch(() => null))
                }
                onDelete={() => m.remove.mutate(e.item.comment!.id)}
                onReact={(emoji, active) => m.react.mutate({ id: e.item.comment!.id, emoji, active })}
              />
            ) : e.kind === 'activity' ? (
              <ActivityLine
                key={e.item.activity!.id}
                who={actorName(e.item, nameOf)}
                at={e.item.at}
                lines={e.lines}
              />
            ) : (
              <FoldedLine
                key={e.entries[0]!.item.activity!.id}
                who={actorName(e.entries[0]!.item, nameOf)}
                at={e.at}
                entries={e.entries}
              />
            ),
          )}
          {!entries.length && filter === 'comments' ? (
            <li className="text-sm text-muted">No comments yet.</li>
          ) : null}
        </ol>
      )}
      {canComment ? (
        <div className="mt-4">
          <CommentEditor
            draftId={task.id}
            submitLabel="Comment"
            onSubmit={async (body) => !!(await m.create.mutateAsync(body).catch(() => null))}
          />
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">You can view this task but not comment on it.</p>
      )}
    </section>
  );
}

function actorName(item: FeedItem, nameOf: (id: string | null | undefined) => string | undefined): string {
  const a = item.activity;
  if (!a) return 'Someone';
  if (a.actor_kind === 'system') return 'Momentum';
  return nameOf(a.actor_id) ?? 'Someone';
}

function ActivityLine({ who, at, lines }: { who: string; at: string; lines: string[] }) {
  return (
    <li className="flex gap-3 pl-1 text-xs text-muted">
      <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-2" />
      <span>
        <span className="font-medium text-ink-2">{who}</span> {lines.join(', ')}
        <span className="text-muted-2"> · {formatRelative(at)}</span>
      </span>
    </li>
  );
}

function FoldedLine({ who, at, entries }: { who: string; at: string; entries: { lines: string[] }[] }) {
  const [open, setOpen] = useState(false);
  const count = entries.reduce((n, e) => n + e.lines.length, 0);
  return (
    <li className="pl-1 text-xs text-muted">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex gap-3 text-left hover:text-ink"
      >
        <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-2" />
        <span>
          <span className="font-medium text-ink-2">{who}</span> made {count} changes
          <span className="text-muted-2"> · {formatRelative(at)}</span>
        </span>
      </button>
      {open ? (
        <ul className="mt-1 ml-5 flex flex-col gap-0.5">
          {entries.flatMap((e, i) => e.lines.map((l, j) => <li key={`${i}-${j}`}>{l}</li>))}
        </ul>
      ) : null}
    </li>
  );
}

function CommentItem({
  comment,
  meId,
  authorName,
  nameOf,
  canReact,
  onEdit,
  onDelete,
  onReact,
}: {
  comment: Comment;
  meId?: string;
  authorName: string;
  nameOf: (id: string) => string | undefined;
  canReact: boolean;
  onEdit: (body: NonNullable<Comment['body']>) => Promise<boolean>;
  onDelete: () => void;
  onReact: (emoji: string, active: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <li className="group/comment flex gap-3" aria-label={`Comment by ${authorName}`}>
      <Avatar name={authorName} size={28} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 text-sm">
          <span className="font-medium">{authorName}</span>
          <time
            className="text-xs text-muted"
            dateTime={comment.created_at}
            title={new Date(comment.created_at).toLocaleString()}
          >
            {formatRelative(comment.created_at)}
          </time>
          {comment.edited_at ? <span className="text-xs text-muted-2">(edited)</span> : null}
          <span className="ml-auto flex gap-0.5 opacity-0 group-hover/comment:opacity-100 focus-within:opacity-100">
            {canReact ? <ReactionPicker onPick={(e) => onReact(e, true)} /> : null}
            {comment.can_edit && !editing ? (
              <IconAction icon={Pencil} label="Edit comment" onClick={() => setEditing(true)} />
            ) : null}
            {comment.can_delete ? (
              <IconAction icon={Trash2} label="Delete comment" onClick={onDelete} />
            ) : null}
          </span>
        </div>
        {editing ? (
          <div className="mt-1">
            <CommentEditor
              draftId={`edit-${comment.id}`}
              initial={comment.body}
              submitLabel="Save"
              focusOnMount
              onCancel={() => setEditing(false)}
              onSubmit={async (body) => {
                const ok = await onEdit(body as NonNullable<Comment['body']>);
                if (ok) setEditing(false);
                return ok;
              }}
            />
          </div>
        ) : (
          <RichTextView doc={comment.body} personName={nameOf} className="mt-0.5 text-sm" />
        )}
        {comment.reactions.length ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {comment.reactions.map((r) => {
              const mine = !!meId && r.user_ids.includes(meId);
              const who = r.user_ids.map((id) => nameOf(id) ?? 'Someone').join(', ');
              return (
                <button
                  key={r.emoji}
                  type="button"
                  disabled={!canReact}
                  aria-pressed={mine}
                  aria-label={`${r.emoji} ${r.user_ids.length}: ${who}`}
                  title={who}
                  onClick={() => onReact(r.emoji, !mine)}
                  className={cn(
                    'flex h-6 items-center gap-1 rounded-full border px-2 text-xs',
                    mine ? 'border-focus bg-selection' : 'border-hairline hover:bg-surface-2',
                  )}
                >
                  <span>{r.emoji}</span>
                  <span className="tabular">{r.user_ids.length}</span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function IconAction({ icon, label, onClick }: { icon: typeof Pencil; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="grid h-6 w-6 place-items-center rounded text-muted hover:bg-surface-2 hover:text-ink"
    >
      <Icon icon={icon} size={14} />
    </button>
  );
}

function ReactionPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Add reaction"
          title="Add reaction"
          className="grid h-6 w-6 place-items-center rounded text-muted hover:bg-surface-2 hover:text-ink"
        >
          <Icon icon={SmilePlus} size={14} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="flex gap-0.5 p-1" align="end">
        {REACTIONS.map((e) => (
          <button
            key={e}
            type="button"
            aria-label={`React ${e}`}
            onClick={() => {
              onPick(e);
              setOpen(false);
            }}
            className="grid h-8 w-8 place-items-center rounded-md text-base hover:bg-surface-2"
          >
            {e}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
