import { useQueryClient } from '@tanstack/react-query';
import { useMe } from '@/features/auth';
import { useChannel } from '@/lib/realtime';

/**
 * S5.0.1: keep the inbox and the topbar bell live on every page. Mounted once in the app shell;
 * a `notification.*` event on `user:<me>` refetches the inbox lists and the unread count (not
 * the notification preferences). Home and My Tasks keep their own `user:<me>` subscription for
 * task events; both share one wire subscription.
 */
export function useLiveNotifications(): void {
  const qc = useQueryClient();
  const meId = useMe().data?.user.id;
  useChannel(meId ? `user:${meId}` : null, (event) => {
    if (event.entity_type !== 'notification') return;
    void qc.invalidateQueries({
      predicate: (q) => q.queryKey[0] === 'notifications' && q.queryKey[1] !== 'prefs',
    });
  });
}
