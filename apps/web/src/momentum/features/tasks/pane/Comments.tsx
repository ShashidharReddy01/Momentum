import { Pencil, SmilePlus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { RichTextView } from '@/components/editor/RichTextView';
import { Avatar } from '@/components/ui/Avatar';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/dates';
import { REACTIONS, useCommentMutations, useComments, type Comment } from '../comments';
import type { TaskDetail } from '../detail';
import { CommentEditor } from './CommentEditor';

/** Comments on a task, with the composer at the bottom. */
export function Comments({ task }: { task: TaskDetail }) {
  const comments = useComments(task.id);
  const meId = useMe().data?.user.id;
  const people = usePeople().data ?? [];
  const nameOf = (id: string | null | undefined) => people.find((p) => p.id === id)?.name;
  const m = useCommentMutations(task.id, meId);
  const canComment = task.my_role === 'admin' || task.my_role === 'editor' || task.my_role === 'commenter';

  return (
    <section aria-label="Comments" className="mt-8">
      <h3 className="section-label mb-2">Comments</h3>
      {comments.isPending ? (
        <Skeleton className="h-12" />
      ) : (
        <ol className="flex flex-col gap-4">
          {(comments.data ?? []).map((c) => (
            <CommentItem
              key={c.id}
              comment={c}
              meId={meId}
              authorName={nameOf(c.author_id) ?? 'Former member'}
              nameOf={nameOf}
              canReact={canComment}
              onEdit={async (body) => !!(await m.edit.mutateAsync({ id: c.id, body }).catch(() => null))}
              onDelete={() => m.remove.mutate(c.id)}
              onReact={(emoji, active) => m.react.mutate({ id: c.id, emoji, active })}
            />
          ))}
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
