import { X } from 'lucide-react';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { IconButton } from '@/components/ui/IconButton';
import { useUi } from '@/stores/ui';

/** Right-side assistant panel. The chat itself arrives in Phase 3. */
export function AskMoPanel() {
  const open = useUi((s) => s.askMoOpen);
  const setOpen = useUi((s) => s.setAskMoOpen);
  if (!open) return null;
  return (
    <aside
      aria-label="Ask Mo"
      className="flex h-full w-[var(--askmo-w)] shrink-0 flex-col border-l border-hair-soft bg-surface shadow-pane"
    >
      <header className="flex h-[var(--topbar-h)] items-center gap-2 border-b border-hair-soft px-4">
        <MoMark size={16} />
        <h2 className="flex-1 font-medium">Ask Mo</h2>
        <IconButton
          icon={X}
          label="Close Ask Mo"
          shortcut="mod+j"
          size="icon-sm"
          onClick={() => setOpen(false)}
        />
      </header>
      <div className="flex-1 overflow-auto p-4">
        <AICallout>
          <p className="font-medium text-ink">Hi, I'm Mo.</p>
          <p className="mt-1">
            Soon you'll be able to ask me about your work, and to have me plan, update and summarize it. I
            arrive in Phase 3.
          </p>
        </AICallout>
      </div>
    </aside>
  );
}
