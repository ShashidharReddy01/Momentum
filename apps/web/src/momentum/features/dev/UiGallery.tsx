import type { ReactNode } from 'react';
import { FolderKanban, Plus, Settings } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { AIBadge, AICallout } from '@/components/common/AI';
import { MockBadge } from '@/components/common/Mock';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Kbd } from '@/components/ui/Kbd';
import { Skeleton } from '@/components/ui/Skeleton';
import { Segmented, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { ApiError } from '@/lib/api/errors';
import { useUi } from '@/stores/ui';

const SWATCHES = [
  'canvas',
  'sidebar',
  'surface',
  'surface-2',
  'hairline',
  'ink',
  'ink-2',
  'muted',
  'muted-2',
  'accent',
  'accent-tint',
  'amber',
  'amber-2',
  'amber-ink',
  'ok',
  'warn',
  'crit',
  'info',
  'mock',
  'focus',
  'selection',
];

/** Dev-only component gallery (S0.3.1): every primitive in the current theme. */
export function UiGallery() {
  const [dialog, setDialog] = useState(false);
  const [mode, setMode] = useState<'week' | 'month'>('week');
  const toggleTheme = useUi((s) => s.toggleTheme);
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-10 px-8 py-10">
      <header className="flex items-center justify-between">
        <div>
          <p className="section-label">Design system</p>
          <h1 className="page-title">Component gallery</h1>
        </div>
        <div className="flex items-center gap-2">
          <MockBadge label="Dev only" />
          <Button onClick={toggleTheme}>Toggle theme</Button>
        </div>
      </header>

      <Section title="Tokens">
        <div className="grid grid-cols-4 gap-2 md:grid-cols-7">
          {SWATCHES.map((s) => (
            <div key={s} className="overflow-hidden rounded-md border border-hairline">
              <div className="h-10" style={{ background: `var(--${s})` }} />
              <div className="px-1.5 py-1 font-mono text-[10.5px]">{s}</div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Typography">
        <p className="page-title">Page title · Inter 20/600</p>
        <p className="text-[15px] font-semibold">Section title · Inter 15/600</p>
        <p className="section-label">Section label · Inter 12/600</p>
        <p>Body text · Inter 14/20. The quick brown fox jumps over the lazy dog.</p>
        <p className="font-mono text-xs tabular">T-1024 · 2026-09-26 · 12:30</p>
        <p className="text-[13px] text-muted">Meta · Inter 13 muted: created by Ana · 2 days ago</p>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">Primary</Button>
          <Button>Ghost</Button>
          <Button variant="text">Text</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="ai">✦ Draft status (AI)</Button>
          <Button loading>Saving</Button>
          <Button size="sm">Small</Button>
          <IconButton icon={Settings} label="Settings" shortcut="mod+," />
        </div>
      </Section>

      <Section title="Inputs, keys, avatars">
        <div className="flex flex-wrap items-center gap-4">
          <Input placeholder="Task name" className="w-64" />
          <Kbd combo="mod+k" />
          <Kbd combo="mod+enter" />
          <div className="flex -space-x-1.5">
            {['Ravi Kumar', 'Ana Souza', 'Priya Nair', 'Tom Becker'].map((n) => (
              <Avatar key={n} name={n} size={26} className="ring-2 ring-surface" />
            ))}
          </div>
          <Avatar name="Herald" size={26} isAgent />
        </div>
      </Section>

      <Section title="Menus, dialogs, tabs, toasts">
        <div className="flex flex-wrap items-center gap-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button>
                <Icon icon={Plus} /> Menu
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuLabel>Create</DropdownMenuLabel>
              <DropdownMenuItem shortcut="q">Task</DropdownMenuItem>
              <DropdownMenuItem>Project</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled hint="Phase 4">
                Rule
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button onClick={() => setDialog(true)}>Open dialog</Button>
          <Button onClick={() => toast('Task completed', { action: { label: 'Undo', onClick: () => {} } })}>
            Toast with undo
          </Button>
          <Segmented
            label="Calendar mode"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'week', label: 'Week' },
              { value: 'month', label: 'Month' },
            ]}
          />
        </div>
        <Tabs defaultValue="list" className="mt-4">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="list">List</TabsTrigger>
            <TabsTrigger value="board">Board</TabsTrigger>
          </TabsList>
          <TabsContent value="list" className="pt-3 text-sm text-muted">
            List view content
          </TabsContent>
        </Tabs>
        <Dialog
          open={dialog}
          onOpenChange={setDialog}
          title="New project"
          description="Projects hold sections and tasks."
        >
          <div className="flex flex-col gap-3 p-5">
            <Input placeholder="Project name" />
            <div className="flex justify-end gap-2">
              <Button onClick={() => setDialog(false)}>Cancel</Button>
              <Button variant="primary">Create</Button>
            </div>
          </div>
        </Dialog>
      </Section>

      <Section title="AI and states">
        <AICallout
          label="Mo · status draft"
          actions={
            <>
              <Button size="sm" variant="ai">
                Apply
              </Button>
              <Button size="sm">Edit</Button>
            </>
          }
        >
          Website Revamp is <strong className="text-warn">at risk</strong>: 3 tasks slipped this week [T-12]
          [T-15].
        </AICallout>
        <p className="mt-3 flex items-center gap-2 text-sm">
          Comment drafted by Mo <AIBadge />
        </p>
        <div className="mt-3 grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-hairline bg-surface">
            <EmptyState
              icon={FolderKanban}
              title="No projects yet"
              action={<Button variant="primary">New project</Button>}
            >
              Create one or import from Asana.
            </EmptyState>
          </div>
          <div className="rounded-lg border border-hairline bg-surface">
            <ErrorState
              error={
                new ApiError({
                  status: 500,
                  code: 'internal_error',
                  detail: 'Server error',
                  request_id: '01J…',
                })
              }
              onRetry={() => {}}
            />
          </div>
          <div className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-4">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-5" />
            <Skeleton className="h-5 w-1/2" />
          </div>
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="section-label mb-3">{title}</h2>
      {children}
    </section>
  );
}
