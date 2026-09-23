import { Dialog } from '@/components/ui/Dialog';
import { Kbd } from '@/components/ui/Kbd';
import { SHORTCUTS } from '@/lib/keyboard';
import { useUi } from '@/stores/ui';

export function ShortcutSheet() {
  const open = useUi((s) => s.shortcutsOpen);
  const setOpen = useUi((s) => s.setShortcutsOpen);
  return (
    <Dialog open={open} onOpenChange={setOpen} title="Keyboard shortcuts">
      <ul className="divide-y divide-hair-soft px-5 py-2">
        {SHORTCUTS.map((s) => (
          <li key={s.combo} className="flex items-center justify-between py-2 text-sm">
            <span className={s.phase ? 'text-muted-2' : undefined}>
              {s.label}
              {s.phase ? <span className="ml-2 text-xs">(Phase {s.phase})</span> : null}
            </span>
            <Kbd combo={s.combo} />
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
