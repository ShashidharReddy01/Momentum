import { useCallback } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';

/** Phase 7.5 (spec §9.4): when a project is marked complete or archived, offer its close-out
 * report (the project page opens the report dialog on `?closeout=1`). Never made on its own. */
export function useOfferCloseout() {
  const navigate = useNavigate();
  return useCallback(
    (projectId: string, name?: string) => {
      toast(name ? `${name} is wrapping up` : 'Wrapping up the project', {
        id: `closeout-${projectId}`,
        duration: 10_000,
        action: {
          label: 'Create close-out report',
          onClick: () => void navigate(`/projects/${projectId}/overview?closeout=1`),
        },
      });
    },
    [navigate],
  );
}
