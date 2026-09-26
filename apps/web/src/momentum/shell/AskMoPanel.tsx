import { Maximize2, SquarePen, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { IconButton } from '@/components/ui/IconButton';
import { MoComposer, MoThread, useMoRuns } from '@/features/ai';
import { useUi } from '@/stores/ui';

/**
 * Right-side assistant panel (⌘J). Typed messages are Ask Mo chat (S3.3.1): answers stream in
 * with citations, and changes Mo suggests show as a PreviewCard. ⌘K "Ask Mo to do this" sends a
 * command (S3.2.2) here too. The same conversation continues until "New chat".
 */
export function AskMoPanel() {
  const open = useUi((s) => s.askMoOpen);
  const setOpen = useUi((s) => s.setAskMoOpen);
  const moRequest = useUi((s) => s.moRequest);
  const takeMoRequest = useUi((s) => s.takeMoRequest);
  const openPalette = useUi((s) => s.openPalette);
  const navigate = useNavigate();
  const mo = useMoRuns();
  const { run, ask } = mo;
  const end = useRef<HTMLDivElement>(null);

  // a request sent from elsewhere (⌘K, or an "Ask Mo about this" button) starts a run here
  useEffect(() => {
    if (!moRequest) return;
    const req = takeMoRequest();
    if (!req) return;
    if (req.kind === 'chat') void ask(req.text);
    else void run(req.text);
  }, [moRequest, takeMoRequest, run, ask]);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [mo.runs]);

  if (!open) return null;
  const busy = mo.runs.some((r) => r.status === 'running');

  return (
    <aside
      aria-label="Ask Mo"
      className="flex h-full w-[var(--askmo-w)] shrink-0 flex-col border-l border-hair-soft bg-surface shadow-pane max-md:fixed max-md:inset-0 max-md:z-30 max-md:w-full max-md:border-l-0"
    >
      <header className="flex h-[var(--topbar-h)] items-center gap-1 border-b border-hair-soft px-4">
        <MoMark size={16} />
        <h2 className="ml-1 flex-1 font-medium">Ask Mo</h2>
        <IconButton icon={SquarePen} label="New chat" size="icon-sm" disabled={busy} onClick={mo.newChat} />
        <IconButton
          icon={Maximize2}
          label="Open chats page"
          size="icon-sm"
          onClick={() => navigate(mo.conversationId ? `/ask/${mo.conversationId}` : '/ask')}
        />
        <IconButton
          icon={X}
          label="Close Ask Mo"
          shortcut="mod+j"
          size="icon-sm"
          onClick={() => setOpen(false)}
        />
      </header>
      <div className="flex-1 space-y-5 overflow-auto p-4">
        {mo.runs.length === 0 ? (
          <AICallout>
            <p className="font-medium text-ink">Hi, I&apos;m Mo.</p>
            <p className="mt-1">
              Ask about your work (“what&apos;s blocking launch?”) and I&apos;ll answer from your workspace,
              with links to what I used. Ask me to change something and I&apos;ll show you the changes first;
              nothing happens until you apply them.
            </p>
          </AICallout>
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
    </aside>
  );
}
