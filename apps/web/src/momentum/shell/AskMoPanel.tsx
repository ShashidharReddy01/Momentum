import { Maximize2, Paperclip, SquarePen, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import {
  contextScreen,
  MoComposer,
  MoThread,
  suggestionsFor,
  useMoFiles,
  useMoRuns,
  useScreen,
  type Screen,
} from '@/features/ai';
import { useMomentumConfig } from '@/lib/config';
import { useUi } from '@/stores/ui';

/**
 * Right-side assistant panel (⌘J). Typed messages are Ask Mo chat (S3.3.1): answers stream in
 * with citations, and changes Mo suggests show as a PreviewCard. ⌘K "Ask Mo to do this" sends a
 * command (S3.2.2) here too. The same conversation continues until "New chat".
 *
 * S3.3.2: an "Ask Mo about this task/project/selection" button starts a new chat pinned to it
 * (a chip shows what; × unpins, back to the current screen), and an empty chat offers starter
 * questions for what the user is looking at.
 */
export function AskMoPanel() {
  const open = useUi((s) => s.askMoOpen);
  const setOpen = useUi((s) => s.setAskMoOpen);
  const moRequest = useUi((s) => s.moRequest);
  const takeMoRequest = useUi((s) => s.takeMoRequest);
  const openPalette = useUi((s) => s.openPalette);
  const moContext = useUi((s) => s.moContext);
  const clearMoContext = useUi((s) => s.clearMoContext);
  const aiEnabled = useMomentumConfig().ai_enabled;
  const navigate = useNavigate();
  const pinned = useMemo(() => (moContext ? contextScreen(moContext) : null), [moContext]);
  const routeScreen = useScreen();
  const [conv, setConv] = useState<{ conversationId: string | null; adopt: (id: string) => void }>({
    conversationId: null,
    adopt: () => {},
  });
  const files = useMoFiles(pinned ?? routeScreen, conv);
  // Phase 7.5: the files added to this chat go with every question (ids of task/project files)
  const screen = useMemo<Screen | null>(() => {
    if (!files.fileIds.length) return pinned;
    const base = pinned ?? routeScreen;
    return { ...base, file_ids: [...new Set([...(base.file_ids ?? []), ...files.fileIds])].slice(0, 5) };
  }, [pinned, routeScreen, files.fileIds]);
  const mo = useMoRuns({ screen });
  const { run, ask, newChat } = mo;
  useEffect(() => {
    setConv({ conversationId: mo.conversationId, adopt: mo.adopt });
  }, [mo.conversationId, mo.adopt]);
  const end = useRef<HTMLDivElement>(null);

  // a request sent from elsewhere (⌘K) starts a run here
  useEffect(() => {
    if (!moRequest) return;
    const req = takeMoRequest();
    if (!req) return;
    if (req.kind === 'chat') void ask(req.text);
    else void run(req.text);
  }, [moRequest, takeMoRequest, run, ask]);
  // "Ask Mo about this": a new chat about it
  useEffect(() => {
    if (moContext) {
      newChat();
      files.clear();
    }
  }, [moContext?.id, newChat]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [mo.runs]);

  if (!open) return null;
  const busy = mo.runs.some((r) => r.status === 'running');
  const suggestions = suggestionsFor(routeScreen, moContext);

  return (
    <aside
      aria-label="Ask Mo"
      className="flex h-full w-[var(--askmo-w)] shrink-0 flex-col border-l border-hair-soft bg-surface shadow-pane max-md:fixed max-md:inset-0 max-md:z-30 max-md:w-full max-md:border-l-0"
    >
      <header className="flex h-[var(--topbar-h)] items-center gap-1 border-b border-hair-soft px-4">
        <MoMark size={16} />
        <h2 className="ml-1 flex-1 font-medium">Ask Mo</h2>
        {aiEnabled ? (
          <>
            <IconButton
              icon={SquarePen}
              label="New chat"
              size="icon-sm"
              disabled={busy}
              onClick={() => {
                clearMoContext();
                newChat();
                files.clear();
              }}
            />
            <IconButton
              icon={Maximize2}
              label="Open chats page"
              size="icon-sm"
              onClick={() => navigate(mo.conversationId ? `/ask/${mo.conversationId}` : '/ask')}
            />
          </>
        ) : null}
        <IconButton
          icon={X}
          label="Close Ask Mo"
          shortcut="mod+j"
          size="icon-sm"
          onClick={() => setOpen(false)}
        />
      </header>
      {!aiEnabled ? (
        <div className="p-4">
          <AICallout>
            <p className="font-medium text-ink">Mo is turned off for this workspace.</p>
            <p className="mt-1">Everything else works as usual. A workspace admin can turn AI on.</p>
          </AICallout>
        </div>
      ) : (
        <>
          {moContext ? (
            <div className="flex items-center gap-2 border-b border-hair-soft px-4 py-2 text-xs">
              <span className="text-muted">About</span>
              <span
                aria-label={`Chat is about ${moContext.label}`}
                className="inline-flex min-w-0 items-center gap-1 rounded-full border border-hairline bg-surface-2 py-0.5 pl-2 pr-1 text-ink"
              >
                <span className="truncate">{moContext.label}</span>
                <button
                  type="button"
                  aria-label="Stop asking about this"
                  onClick={clearMoContext}
                  className="grid h-4 w-4 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink"
                >
                  <Icon icon={X} size={11} />
                </button>
              </span>
            </div>
          ) : null}
          <div className="flex-1 space-y-5 overflow-auto p-4">
            {mo.runs.length === 0 ? (
              <>
                <AICallout>
                  <p className="font-medium text-ink">Hi, I&apos;m Mo.</p>
                  <p className="mt-1">
                    Ask about your work and I&apos;ll answer from your workspace, with links to what I used.
                    Ask me to change something and I&apos;ll show you the changes first; nothing happens until
                    you apply them.
                  </p>
                </AICallout>
                <div role="group" aria-label="Suggested questions" className="flex flex-wrap gap-1.5">
                  {suggestions.map((q) => (
                    <Button key={q} size="sm" variant="ghost" onClick={() => void ask(q)}>
                      {q}
                    </Button>
                  ))}
                </div>
              </>
            ) : null}
            <MoThread
              runs={mo.runs}
              onEdit={(r) => openPalette(r.text)}
              onChoose={(r, choice) =>
                void (r.kind === 'chat' ? ask(choice) : run(`${r.text} (I mean ${choice})`))
              }
              onRated={(r, rating) => mo.rate(r.id, rating)}
            />
            <div ref={end} />
          </div>
          {files.chips.length || files.uploading ? (
            <div
              role="group"
              aria-label="Files in this chat"
              className="flex flex-wrap items-center gap-1.5 border-t border-hair-soft px-3 pt-2 text-xs"
            >
              {files.chips.map((c) => (
                <span
                  key={c.id}
                  className="inline-flex min-w-0 items-center gap-1 rounded-full border border-hairline bg-surface-2 py-0.5 pl-2 pr-1 text-ink"
                  title={c.where === 'chat' ? 'Only in this chat' : undefined}
                >
                  <Icon icon={Paperclip} size={11} className="shrink-0 text-muted" />
                  <span className="max-w-[12rem] truncate">{c.name}</span>
                  {c.where === 'file' ? (
                    <button
                      type="button"
                      aria-label={`Remove ${c.name} from this chat`}
                      onClick={() => files.remove(c.id)}
                      className="grid h-4 w-4 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink"
                    >
                      <Icon icon={X} size={11} />
                    </button>
                  ) : null}
                </span>
              ))}
              {files.uploading ? <span className="text-muted">Attaching…</span> : null}
            </div>
          ) : null}
          <MoComposer
            onSend={(text) => void ask(text)}
            busy={busy || files.uploading}
            onAttach={(list) => void files.attach(list)}
            onFileChip={(f) => files.add({ ...f, where: 'file' })}
          />
        </>
      )}
    </aside>
  );
}
