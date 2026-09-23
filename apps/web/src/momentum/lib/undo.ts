import { useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { toast } from 'sonner';
import { useApi } from '@/providers/api';
import { toastError } from './toast';

export interface UndoMeta {
  activity_id?: string | null;
  batch_id?: string | null;
}

/** Returns `notify(message, meta)`: a toast with an Undo action for a completed mutation. */
export function useUndoToast() {
  const api = useApi();
  const qc = useQueryClient();
  return useCallback(
    (message: string, meta: UndoMeta | undefined, onUndone?: () => void) => {
      const activityId = meta?.activity_id ?? undefined;
      const batchId = meta?.batch_id ?? undefined;
      if (!activityId && !batchId) {
        toast.success(message);
        return;
      }
      toast.success(message, {
        duration: 6000,
        action: {
          label: 'Undo',
          onClick: async () => {
            try {
              await api.POST('/api/v1/undo', {
                body: batchId ? { batch_id: batchId } : { activity_id: activityId },
              });
              await qc.invalidateQueries();
              onUndone?.();
              toast('Undone');
            } catch (e) {
              toastError(e, "Couldn't undo");
            }
          },
        },
      });
    },
    [api, qc],
  );
}
