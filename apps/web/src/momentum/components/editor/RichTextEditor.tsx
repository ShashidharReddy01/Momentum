import { Markdown } from '@tiptap/markdown';
import { TaskItem } from '@tiptap/extension-task-item';
import { TaskList } from '@tiptap/extension-task-list';
import { Placeholder } from '@tiptap/extensions';
import { EditorContent, useEditor, useEditorState, type Editor, type JSONContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {
  Bold,
  Code,
  Heading2,
  Italic,
  Link2,
  List,
  ListChecks,
  ListOrdered,
  SquareCode,
  Strikethrough,
} from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/Popover';
import { cn } from '@/lib/cn';
import { useWritingHelp, type WritingHelp } from './WritingHelp';

const SAFE_PROTOCOLS = ['http', 'https', 'mailto'];
export const isSafeUrl = (url: string) => {
  try {
    const u = new URL(url, 'https://x.invalid');
    return SAFE_PROTOCOLS.includes(u.protocol.replace(':', ''));
  } catch {
    return false;
  }
};
// Plain-text paste that looks like Markdown is converted (headings, lists, checklists, code, links).
const MARKDOWN_HINT = /^(#{1,3} |[-*+] |\d+\. |- \[[ xX]\] |> |```)|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^)\s]+\)/m;

/**
 * Rich text editor (Tiptap): headings, lists, checklists, links, code; Markdown paste.
 * Content is JSON; the server re-validates it (core/richtext.py). `revision` replaces the content
 * when it changes (draft restore, "use theirs", someone else's edit), otherwise typing is local.
 */
export function RichTextEditor({
  content,
  revision,
  editable,
  placeholder,
  label,
  onChange,
  onBlur,
  className,
  writingHelp,
}: {
  content: JSONContent | null;
  revision: number;
  editable: boolean;
  placeholder: string;
  label: string;
  onChange: (doc: JSONContent) => void;
  onBlur?: () => void;
  className?: string;
  /** S3.4.4: Mo's writing help in the toolbar (the host supplies the AI call; omit = none). */
  writingHelp?: WritingHelp;
}) {
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onBlurRef = useRef(onBlur);
  onBlurRef.current = onBlur;
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        link: {
          openOnClick: false,
          autolink: true,
          protocols: SAFE_PROTOCOLS,
          isAllowedUri: (url) => isSafeUrl(url),
          HTMLAttributes: { rel: 'noopener noreferrer nofollow', target: '_blank' },
        },
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Placeholder.configure({ placeholder }),
      Markdown,
    ],
    content: content ?? '',
    editable,
    immediatelyRender: true,
    shouldRerenderOnTransaction: false,
    editorProps: {
      attributes: { 'aria-label': label, role: 'textbox', 'aria-multiline': 'true', class: 'mo-prose' },
      handlePaste: (_view, event) => {
        const data = event.clipboardData;
        if (!data || data.types.includes('text/html')) return false;
        const text = data.getData('text/plain');
        if (!text || !MARKDOWN_HINT.test(text)) return false;
        editorRef.current?.commands.insertContent(text, { contentType: 'markdown' });
        return true;
      },
    },
    onUpdate: ({ editor: e }) => onChangeRef.current(e.getJSON()),
    onBlur: () => onBlurRef.current?.(),
  });
  const editorRef = useRef<Editor | null>(null);
  editorRef.current = editor;

  // Replace content only when the owner says so (new revision), never while typing.
  const applied = useRef(revision);
  useEffect(() => {
    if (!editor || applied.current === revision) return;
    applied.current = revision;
    editor.commands.setContent(content ?? '', { emitUpdate: false });
  }, [editor, revision, content]);
  useEffect(() => {
    // false: setEditable would otherwise emit an update, which looks like an edit
    editor?.setEditable(editable, false);
  }, [editor, editable]);

  const help = useWritingHelp(editor, editable ? writingHelp : undefined);
  return (
    <div className={cn('group/editor rounded-md', className)}>
      {editable && editor ? <Toolbar editor={editor} extra={help.menu} /> : null}
      {help.panel}
      <EditorContent editor={editor} />
    </div>
  );
}

function Toolbar({ editor, extra }: { editor: Editor; extra?: ReactNode }) {
  const active = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive('bold'),
      italic: e.isActive('italic'),
      strike: e.isActive('strike'),
      code: e.isActive('code'),
      h2: e.isActive('heading', { level: 2 }),
      bullet: e.isActive('bulletList'),
      ordered: e.isActive('orderedList'),
      task: e.isActive('taskList'),
      codeBlock: e.isActive('codeBlock'),
      link: e.isActive('link'),
      focused: e.isFocused,
    }),
  });
  const [linkOpen, setLinkOpen] = useState(false);
  const [href, setHref] = useState('');
  const chain = () => editor.chain().focus();
  const items = [
    { icon: Bold, label: 'Bold', key: 'mod+B', on: active.bold, run: () => chain().toggleBold().run() },
    {
      icon: Italic,
      label: 'Italic',
      key: 'mod+I',
      on: active.italic,
      run: () => chain().toggleItalic().run(),
    },
    {
      icon: Strikethrough,
      label: 'Strikethrough',
      on: active.strike,
      run: () => chain().toggleStrike().run(),
    },
    { icon: Code, label: 'Inline code', on: active.code, run: () => chain().toggleCode().run() },
    { icon: Heading2, label: 'Heading', on: active.h2, run: () => chain().toggleHeading({ level: 2 }).run() },
    { icon: List, label: 'Bulleted list', on: active.bullet, run: () => chain().toggleBulletList().run() },
    {
      icon: ListOrdered,
      label: 'Numbered list',
      on: active.ordered,
      run: () => chain().toggleOrderedList().run(),
    },
    { icon: ListChecks, label: 'Checklist', on: active.task, run: () => chain().toggleTaskList().run() },
    {
      icon: SquareCode,
      label: 'Code block',
      on: active.codeBlock,
      run: () => chain().toggleCodeBlock().run(),
    },
  ];
  const applyLink = () => {
    const url = href.trim();
    if (!url) chain().extendMarkRange('link').unsetLink().run();
    else if (isSafeUrl(url)) chain().extendMarkRange('link').setLink({ href: url }).run();
    setLinkOpen(false);
  };
  return (
    <div
      role="toolbar"
      aria-label="Formatting"
      className={cn(
        'mb-1 flex flex-wrap gap-0.5 transition-opacity',
        active.focused || linkOpen
          ? 'opacity-100'
          : 'opacity-0 group-focus-within/editor:opacity-100 group-hover/editor:opacity-60',
      )}
    >
      {items.map((it) => (
        <button
          key={it.label}
          type="button"
          aria-label={it.label}
          aria-pressed={it.on}
          title={it.label}
          onMouseDown={(e) => e.preventDefault()}
          onClick={it.run}
          className={cn(
            'grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink',
            it.on && 'bg-surface-2 text-ink',
          )}
        >
          <Icon icon={it.icon} size={15} />
        </button>
      ))}
      <Popover open={linkOpen} onOpenChange={setLinkOpen}>
        <PopoverAnchor asChild>
          <button
            type="button"
            aria-label="Link"
            aria-pressed={active.link}
            title="Link"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              setHref((editor.getAttributes('link').href as string | undefined) ?? '');
              setLinkOpen(true);
            }}
            className={cn(
              'grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink',
              active.link && 'bg-surface-2 text-ink',
            )}
          >
            <Icon icon={Link2} size={15} />
          </button>
        </PopoverAnchor>
        <PopoverContent className="w-72 p-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              applyLink();
            }}
          >
            <input
              aria-label="Link URL"
              placeholder="https://…"
              value={href}
              // eslint-disable-next-line jsx-a11y/no-autofocus -- opened to type a URL
              autoFocus
              onChange={(e) => setHref(e.target.value)}
              className="h-8 w-full rounded-md border border-hairline bg-surface px-2 text-sm outline-none focus:border-focus"
            />
            {href && !isSafeUrl(href.trim()) ? (
              <p className="mt-1 text-xs text-crit">Use an http(s) or mailto link</p>
            ) : null}
          </form>
        </PopoverContent>
      </Popover>
      {extra}
    </div>
  );
}
