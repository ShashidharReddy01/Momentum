import { Maximize2, SquarePen, X } from 'lucide-react';
import { useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { contextScreen, MoComposer, MoThread, suggestionsFor, useMoRuns, useScreen } from '@/features/ai';
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
  const mo = useMoRuns({ screen: pinned });
  const { run, ask, newChat } = mo;
  const routeScreen = useScreen();
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
    if (moContext) newChat();
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
          <MoComposer onSend={(text) => void ask(text)} busy={busy} />
        </>
      )}
    </aside>
  );
}
