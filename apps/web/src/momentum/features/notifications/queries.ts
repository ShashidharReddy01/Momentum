import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Notification = components['schemas']['NotificationOut'];
export type NotificationPrefs = components['schemas']['NotificationPrefsOut'];

export const notificationKeys = {
  list: (archived: boolean) => ['notifications', { archived }] as const,
  unreadCount: ['notifications', 'unread-count'] as const,
  prefs: ['notifications', 'prefs'] as const,
};

const invalidateAll = (qc: ReturnType<typeof useQueryClient>) =>
  void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'notifications' });

export function useNotifications(archived = false) {
  const api = useApi();
  return useQuery({
    queryKey: notificationKeys.list(archived),
    queryFn: async () =>
      (await api.GET('/api/v1/notifications', { params: { query: { archived } } })).data!.data,
  });
}

export function useUnreadCount() {
  const api = useApi();
  return useQuery({
    queryKey: notificationKeys.unreadCount,
    queryFn: async () => (await api.GET('/api/v1/notifications/unread-count')).data!.count,
  });
}

export function useNotificationPrefs() {
  const api = useApi();
  return useQuery({
    queryKey: notificationKeys.prefs,
    queryFn: async () => (await api.GET('/api/v1/me/prefs/notifications')).data!,
  });
}

export function useSetNotificationPrefs() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (prefs: NotificationPrefs) =>
      (await api.PUT('/api/v1/me/prefs/notifications', { body: prefs })).data!,
    onSuccess: (data) => qc.setQueryData(notificationKeys.prefs, data),
    onError: (e) => toastError(e, "Couldn't save your notification preferences"),
  });
}

/** Read/unread, archive/unarchive (S2.5.2: keyboard `E` archives, `U` marks unread). Optimistic —
 * the inbox list and the bell's unread count both update immediately. */
export function useNotificationMutations() {
  const api = useApi();
  const qc = useQueryClient();

  const setRead = useMutation({
    mutationFn: async (v: { id: string; read: boolean }) =>
      (
        await api.POST(
          v.read
            ? '/api/v1/notifications/{notification_id}/read'
            : '/api/v1/notifications/{notification_id}/unread',
          { params: { path: { notification_id: v.id } } },
        )
      ).data!,
    onMutate: (v) => {
      for (const archived of [false, true]) {
        qc.setQueryData<Notification[]>(notificationKeys.list(archived), (old) =>
          old?.map((n) => (n.id === v.id ? { ...n, read_at: v.read ? new Date().toISOString() : null } : n)),
        );
      }
    },
    onError: (e) => toastError(e, "Couldn't update that notification"),
    onSettled: () => invalidateAll(qc),
  });

  const setArchived = useMutation({
    mutationFn: async (v: { id: string; archived: boolean }) =>
      (
        await api.POST(
          v.archived
            ? '/api/v1/notifications/{notification_id}/archive'
            : '/api/v1/notifications/{notification_id}/unarchive',
          { params: { path: { notification_id: v.id } } },
        )
      ).data!,
    onMutate: (v) => {
      qc.setQueryData<Notification[]>(notificationKeys.list(false), (old) =>
        v.archived ? old?.filter((n) => n.id !== v.id) : old,
      );
      qc.setQueryData<Notification[]>(notificationKeys.list(true), (old) =>
        !v.archived ? old?.filter((n) => n.id !== v.id) : old,
      );
    },
    onError: (e) => toastError(e, "Couldn't update that notification"),
    onSettled: () => invalidateAll(qc),
  });

  return { setRead, setArchived };
}
