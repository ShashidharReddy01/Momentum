import { useEffect } from 'react';
import { useUi } from '@/stores/ui';

/** Set the top-bar breadcrumb for the current page (e.g. ["Product", "Website Revamp"]). */
export function useCrumbs(crumbs: (string | undefined)[] | null): void {
  const setCrumbs = useUi((s) => s.setCrumbs);
  const key = crumbs ? crumbs.join('\u0000') : '';
  useEffect(() => {
    const clean = crumbs?.filter((c): c is string => Boolean(c)) ?? null;
    setCrumbs(clean && clean.length ? clean : null);
    return () => setCrumbs(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, setCrumbs]);
}
