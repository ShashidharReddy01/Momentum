import { Mention } from '@tiptap/extension-mention';
import { Placeholder } from '@tiptap/extensions';
import { EditorContent, useEditor, type Editor, type JSONContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import type { SuggestionKeyDownProps, SuggestionProps } from '@tiptap/suggestion';
import { FolderKanban, SquareCheck } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { isSafeUrl } from '@/components/editor/RichTextEditor';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Kbd } from '@/components/ui/Kbd';
import { cn } from '@/lib/cn';
import { useApi } from '@/providers/api';
import { usePortalContainer } from '@/providers/portal';

interface Item {
  kind: 'user' | 'task' | 'project';
  id: string;
  label: string;
  sub?: string;
  color?: string | null;
}

interface SuggestState {
  items: Item[];
  index: number;
  rect: DOMRect | null;
  command: (item: { id: string; label: string; kind: string }) => void;
}

const draftKey = (key: string) => `momentum.draft.comment.${key}`;
const isEmpty = (doc: JSONContent | null | undefined) => {
  if (!doc?.content?.length) return true;
  return doc.content.every((n) => n.type === 'paragraph' && !n.content?.length);
};

/**
 * Comment editor: bold/italic/lists/links, @mentions of people, tasks and projects, ⌘Enter to
 * send. The text is kept on this device until it's posted (or the edit is saved).
 */
export function CommentEditor({
  draftId,
  initial,
  submitLabel,
  placeholder = 'Add a comment… @ to mention',
  onSubmit,
  onCancel,
  focusOnMount,
}: {
  /** Key for the local draft: the task id (new comment) or `edit-<comment id>`. */
  draftId: string;
  initial?: JSONContent | null;
  submitLabel: string;
  placeholder?: string;
  /** Resolves true when saved (the editor then clears and drops the draft). */
  onSubmit: (doc: JSONContent) => Promise<boolean>;
  onCancel?: () => void;
  focusOnMount?: boolean;
}) {
  const api = useApi();
  const portal = usePortalContainer();
  const [suggest, setSuggest] = useState<SuggestState | null>(null);
  const suggestRef = useRef<SuggestState | null>(null);
  suggestRef.current = suggest;
  const [empty, setEmpty] = useState(true);
  const [busy, setBusy] = useState(false);
  const editorRef = useRef<Editor | null>(null);

  const readDraft = (): JSONContent | null => {
    try {
      const raw = localStorage.getItem(draftKey(draftId));
      return raw ? (JSON.parse(raw) as JSONContent) : null;
    } catch {
      return null;
    }
  };

  const search = async (query: string): Promise<Item[]> => {
    try {
      const res = (await api.GET('/api/v1/mentions/search', { params: { query: { q: query } } })).data!;
      return [
        ...res.users.map((u) => ({ kind: 'user' as const, id: u.id, label: u.name, sub: u.email })),
        ...res.tasks.map((t) => ({ kind: 'task' as const, id: t.id, label: t.title, sub: t.key })),
        ...res.projects.map((p) => ({ kind: 'project' as const, id: p.id, label: p.name, color: p.color })),
      ];
    } catch {
      return [];
    }
  };

  const submit = async () => {
    const editor = editorRef.current;
    if (!editor || busy) return;
    const doc = editor.getJSON();
    if (isEmpty(doc)) return;
    setBusy(true);
    const ok = await onSubmit(doc).catch(() => false);
    setBusy(false);
    if (ok) {
      try {
        localStorage.removeItem(draftKey(draftId));
      } catch {
        /* ignore */
      }
      editor.commands.clearContent(true);
      setEmpty(true);
    }
  };
  const submitRef = useRef(submit);
  submitRef.current = submit;

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        horizontalRule: false,
        link: {
          openOnClick: false,
          autolink: true,
          protocols: ['http', 'https', 'mailto'],
          isAllowedUri: (url) => isSafeUrl(url),
          HTMLAttributes: { rel: 'noopener noreferrer nofollow', target: '_blank' },
        },
      }),
      Placeholder.configure({ placeholder }),
      Mention.extend({
        addAttributes() {
          return { ...this.parent?.(), kind: { default: 'user' } };
        },
      }).configure({
        HTMLAttributes: { class: 'mo-mention' },
        renderText: ({ node }) => `@${node.attrs.label ?? ''}`,
        renderHTML: ({ node, options }) => [
          'span',
          { ...options.HTMLAttributes, 'data-kind': node.attrs.kind },
          `${node.attrs.kind === 'user' ? '@' : ''}${node.attrs.label ?? ''}`,
        ],
        suggestion: {
          char: '@',
          allowSpaces: false,
          items: ({ query }) => search(query),
          command: ({ editor: e, range, props }) => {
            const item = props as { id: string; label: string; kind: string };
            e.chain()
              .focus()
              .insertContentAt(range, [
                { type: 'mention', attrs: { id: item.id, label: item.label, kind: item.kind } },
                { type: 'text', text: ' ' },
              ])
              .run();
          },
          render: () => ({
            onStart: (p: SuggestionProps<Item>) =>
              setSuggest({ items: p.items, index: 0, rect: p.clientRect?.() ?? null, command: p.command }),
            onUpdate: (p: SuggestionProps<Item>) =>
              setSuggest({ items: p.items, index: 0, rect: p.clientRect?.() ?? null, command: p.command }),
            onKeyDown: ({ event }: SuggestionKeyDownProps) => {
              const s = suggestRef.current;
              if (!s) return false;
              if (event.key === 'Escape') {
                setSuggest(null);
                return true;
              }
              if (!s.items.length) return false;
              if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                const d = event.key === 'ArrowDown' ? 1 : -1;
                setSuggest({ ...s, index: (s.index + d + s.items.length) % s.items.length });
                return true;
              }
              if (event.key === 'Enter' || event.key === 'Tab') {
                const it = s.items[s.index];
                if (it) s.command({ id: it.id, label: it.label, kind: it.kind });
                return true;
              }
              return false;
            },
            onExit: () => setSuggest(null),
          }),
        },
      }),
    ],
    content: initial ?? readDraft() ?? '',
    immediatelyRender: true,
    shouldRerenderOnTransaction: false,
    autofocus: focusOnMount ? 'end' : false,
    editorProps: {
      attributes: {
        'aria-label': submitLabel === 'Comment' ? 'New comment' : 'Edit comment',
        class: 'mo-prose mo-prose-compact',
      },
      handleKeyDown: (_view, event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
          event.preventDefault();
          void submitRef.current();
          return true;
        }
        if (event.key === 'Escape' && onCancel && !suggestRef.current) {
          onCancel();
          return true;
        }
        return false;
      },
    },
    onCreate: ({ editor: e }) => setEmpty(isEmpty(e.getJSON())),
    onUpdate: ({ editor: e }) => {
      const doc = e.getJSON();
      setEmpty(isEmpty(doc));
      try {
        if (isEmpty(doc)) localStorage.removeItem(draftKey(draftId));
        else localStorage.setItem(draftKey(draftId), JSON.stringify(doc));
      } catch {
        /* storage blocked: the editor still holds the text */
      }
    },
  });
  editorRef.current = editor;
  useEffect(() => () => setSuggest(null), []);

  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-2 focus-within:border-focus">
      <EditorContent editor={editor} className="min-h-[2.5rem] text-sm" />
      <div className="mt-1 flex items-center justify-end gap-2">
        <span className="mr-auto text-[11px] text-muted-2">
          <Kbd combo="mod+enter" /> to send
        </span>
        {onCancel ? (
          <Button size="sm" variant="text" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
        <Button size="sm" variant="primary" disabled={empty} loading={busy} onClick={() => void submit()}>
          {submitLabel}
        </Button>
      </div>
      {suggest && suggest.rect
        ? createPortal(
            <ul
              role="listbox"
              aria-label="Mention"
              className="fixed z-50 max-h-72 w-72 overflow-auto rounded-lg bg-surface p-1 shadow-pop"
              style={{ top: suggest.rect.bottom + 6, left: suggest.rect.left }}
            >
              {suggest.items.length === 0 ? (
                <li className="px-3 py-2 text-sm text-muted">No matches</li>
              ) : (
                suggest.items.map((it, i) => (
                  <li
                    key={`${it.kind}-${it.id}`}
                    role="option"
                    aria-selected={i === suggest.index}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      suggest.command({ id: it.id, label: it.label, kind: it.kind });
                    }}
                    className={cn(
                      'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm',
                      i === suggest.index && 'bg-surface-2',
                    )}
                  >
                    {it.kind === 'user' ? (
                      <Avatar name={it.label} size={20} />
                    ) : (
                      <Icon
                        icon={it.kind === 'task' ? SquareCheck : FolderKanban}
                        size={15}
                        className="text-muted"
                      />
                    )}
                    <span className="min-w-0 flex-1 truncate">{it.label}</span>
                    {it.sub ? <span className="truncate text-xs text-muted">{it.sub}</span> : null}
                  </li>
                ))
              )}
            </ul>,
            portal ?? document.body,
          )
        : null}
    </div>
  );
}
