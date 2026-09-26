import type { Editor } from '@tiptap/react';
import { useState } from 'react';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';

export type WriteAction = 'improve' | 'shorten' | 'fix_grammar' | 'tone' | 'translate';
export interface WriteRequest {
  action: WriteAction;
  text: string;
  tone?: 'friendly' | 'formal' | 'direct' | 'confident';
  language?: string;
}
/** The host supplies the AI call (the editor itself knows nothing about the API). */
export type WritingHelp = (req: WriteRequest) => Promise<string>;

const LANGUAGES = ['English', 'Spanish', 'Portuguese', 'French', 'German', 'Hindi', 'Japanese', 'Chinese'];
const TONES = [
  ['friendly', 'Friendlier'],
  ['formal', 'More formal'],
  ['direct', 'More direct'],
  ['confident', 'More confident'],
] as const;

interface Pending {
  req: WriteRequest;
  from: number;
  to: number;
  original: string;
  label: string;
  status: 'working' | 'ready' | 'error';
  result?: string;
  error?: string;
}

/**
 * S3.4.4 writing help: a "Mo" menu in the editor toolbar. It works on the selection, or on the
 * whole text when nothing is selected. Mo's rewrite is shown as a suggestion (AI callout) under
 * the toolbar; nothing changes until "Replace". If the text under the selection changed in the
 * meantime, the suggestion is not applied (ask again), so Mo never overwrites newer typing.
 * Rewrites come back as Markdown (paragraphs, bullets, bold) and are inserted as such.
 */
export function useWritingHelp(editor: Editor | null, help: WritingHelp | undefined) {
  const [pending, setPending] = useState<Pending | null>(null);

  const run = (req: WriteRequest, range: { from: number; to: number }, label: string) => {
    if (!help) return;
    const p: Pending = { req, ...range, original: req.text, label, status: 'working' };
    setPending(p);
    help(req).then(
      (result) => setPending((cur) => (cur === p ? { ...p, status: 'ready', result } : cur)),
      (e: unknown) =>
        setPending((cur) =>
          cur === p
            ? {
                ...p,
                status: 'error',
                error: e instanceof Error ? e.message : 'Mo is unavailable right now.',
              }
            : cur,
        ),
    );
  };

  const start = (req: Omit<WriteRequest, 'text'>, label: string) => {
    if (!editor) return;
    const { from, to, empty } = editor.state.selection;
    const range = empty ? { from: 0, to: editor.state.doc.content.size } : { from, to };
    const text = editor.state.doc.textBetween(range.from, range.to, '\n').trim();
    if (text) run({ ...req, text }, range, label);
  };

  const accept = () => {
    if (!editor || !pending?.result) return;
    const now = editor.state.doc.textBetween(
      Math.min(pending.from, editor.state.doc.content.size),
      Math.min(pending.to, editor.state.doc.content.size),
      '\n',
    );
    if (now.trim() !== pending.original) {
      setPending({ ...pending, status: 'error', error: 'The text changed since you asked. Ask Mo again.' });
      return;
    }
    editor
      .chain()
      .focus()
      .insertContentAt({ from: pending.from, to: pending.to }, pending.result, { contentType: 'markdown' })
      .run();
    setPending(null);
  };

  const menu =
    editor && help ? (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label="Ask Mo to rewrite"
            title="Ask Mo to rewrite (the selection, or everything)"
            onMouseDown={(e) => e.preventDefault()}
            className="flex h-7 items-center gap-1 rounded-md px-1.5 text-xs text-amber-ink hover:bg-surface-2"
          >
            <MoMark size={13} /> Mo
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent onCloseAutoFocus={(e) => e.preventDefault()}>
          <DropdownMenuItem onSelect={() => start({ action: 'improve' }, 'Improved')}>
            Improve writing
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => start({ action: 'shorten' }, 'Shorter')}>
            Make shorter
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => start({ action: 'fix_grammar' }, 'Fixed spelling and grammar')}>
            Fix spelling & grammar
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Tone</DropdownMenuLabel>
          {TONES.map(([tone, label]) => (
            <DropdownMenuItem key={tone} onSelect={() => start({ action: 'tone', tone }, label)}>
              {label}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Translate to</DropdownMenuLabel>
          {LANGUAGES.map((language) => (
            <DropdownMenuItem
              key={language}
              onSelect={() => start({ action: 'translate', language }, `In ${language}`)}
            >
              {language}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    ) : null;

  const panel = pending ? (
    <AICallout
      label={`Mo suggests: ${pending.label}`}
      className="mb-2"
      actions={
        <>
          {pending.status === 'ready' ? (
            <Button size="sm" variant="ai" onClick={accept}>
              Replace
            </Button>
          ) : null}
          {pending.status !== 'working' ? (
            <Button size="sm" variant="ghost" onClick={() => run(pending.req, pending, pending.label)}>
              Try again
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
            {pending.status === 'working' ? 'Cancel' : 'Reject'}
          </Button>
        </>
      }
    >
      {pending.status === 'working' ? (
        <p role="status">Mo is rewriting…</p>
      ) : pending.status === 'error' ? (
        <p role="alert" className="text-crit">
          {pending.error}
        </p>
      ) : (
        <p className="whitespace-pre-wrap" aria-label="Suggested text">
          {pending.result}
        </p>
      )}
    </AICallout>
  ) : null;

  return { menu, panel };
}
