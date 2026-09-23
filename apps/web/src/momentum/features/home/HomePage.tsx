import { CheckSquare, FolderKanban, Hourglass } from 'lucide-react';
import type { ReactNode } from 'react';
import { EmptyState } from '@/components/common/States';
import { useMe } from '@/features/auth';

function greeting(date: Date): string {
  const h = date.getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export function HomePage() {
  const me = useMe();
  const now = new Date();
  const first = me.data?.user.name.split(' ')[0] ?? '';
  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <h1 className="page-title">
        {greeting(now)}, {first}
      </h1>
      <p className="mt-0.5 text-sm text-muted">
        {now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
      </p>
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        <HomeCard title="My priorities">
          <EmptyState icon={CheckSquare} title="No tasks yet">
            Your next tasks will show here once projects exist.
          </EmptyState>
        </HomeCard>
        <HomeCard title="Recent projects">
          <EmptyState icon={FolderKanban} title="No projects yet" />
        </HomeCard>
        <HomeCard title="Waiting on others">
          <EmptyState icon={Hourglass} title="Nothing waiting" />
        </HomeCard>
      </div>
    </div>
  );
}

function HomeCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-hairline bg-surface p-4">
      <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
      {children}
    </section>
  );
}
