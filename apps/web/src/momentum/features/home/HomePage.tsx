import type { ReactNode } from 'react';
import { CheckSquare, FolderKanban, Hourglass } from 'lucide-react';
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
    <div className="mx-auto max-w-5xl px-8 py-10">
      <p className="reveal eyebrow">
        {now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
      </p>
      <h1 className="reveal mt-1 font-serif text-[32px] leading-[38px]">
        {greeting(now)}, {first}
      </h1>
      <div className="mt-8 grid gap-4 md:grid-cols-3">
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
    <section className="reveal rounded-xl border border-hairline bg-paper p-4">
      <h2 className="eyebrow">{title}</h2>
      {children}
    </section>
  );
}
