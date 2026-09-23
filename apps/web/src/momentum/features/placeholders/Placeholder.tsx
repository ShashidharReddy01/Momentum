import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { EmptyState } from '@/components/common/States';

/** Honest placeholder for screens delivered in a later phase. */
export function Placeholder({
  icon,
  title,
  phase,
  children,
}: {
  icon: LucideIcon;
  title: string;
  phase: number;
  children?: ReactNode;
}) {
  return (
    <div className="px-8 py-10">
      <h1 className="font-serif text-[22px] leading-7">{title}</h1>
      <EmptyState icon={icon} title={`${title} arrives in Phase ${phase}`}>
        {children}
      </EmptyState>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div className="px-8 py-16 text-center">
      <h1 className="font-serif text-2xl">Not found</h1>
      <p className="mt-2 text-sm text-muted">This page doesn't exist, or you don't have access to it.</p>
    </div>
  );
}
