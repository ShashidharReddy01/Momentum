import { FileText } from 'lucide-react';
import { lazy, Suspense, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';

const ReportDialog = lazy(() => import('@/features/reports').then((m) => ({ default: m.ReportDialog })));

/** Phase 7.5 (spec §6.3): the dashboard as a report (each chart with its numbers, as you). */
export function ReportButton({ dashboardId, name }: { dashboardId: string; name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="text" onClick={() => setOpen(true)}>
        <Icon icon={FileText} size={14} /> Create report
      </Button>
      {open ? (
        <Suspense fallback={null}>
          <ReportDialog open onOpenChange={setOpen} scope={{ dashboardId }} name={name} />
        </Suspense>
      ) : null}
    </>
  );
}
