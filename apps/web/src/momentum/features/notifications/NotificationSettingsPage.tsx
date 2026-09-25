import { Bell } from 'lucide-react';
import { Link } from 'react-router';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useNotificationPrefs, useSetNotificationPrefs, type NotificationPrefs } from './queries';

type Channel = NotificationPrefs['assigned'];
const CHANNEL_KINDS = ['assigned', 'mentioned', 'commented', 'completed', 'due_soon', 'overdue'] as const;

const KIND_LABEL: Record<(typeof CHANNEL_KINDS)[number], string> = {
  assigned: 'Assigned to me',
  mentioned: 'Mentioned in a comment',
  commented: 'Comment on a task I follow',
  completed: 'A task I created is completed',
  due_soon: 'Due today',
  overdue: 'Overdue',
};

const CHANNEL_LABEL: Record<Channel, string> = {
  in_app: 'In-app',
  email: 'Email (coming soon)',
  slack: 'Slack (coming soon)',
  off: 'Off',
};
const CHANNEL_OPTIONS = Object.keys(CHANNEL_LABEL) as Channel[];

/** S2.5.3: per-kind channel choice plus a digest-time preference. Only "in_app" delivers
 * anything today — the backend records "email"/"slack" as chosen-but-not-yet-active, so
 * picking one behaves like "off" until those senders exist (see `NotificationChannel`'s
 * docstring in `domain/notifications/schemas.py`). The digest time is likewise stored only,
 * for the Pulse agent's daily digest in a future phase — nothing reads it yet. */
export function NotificationSettingsPage() {
  const prefs = useNotificationPrefs();
  const setPrefs = useSetNotificationPrefs();

  const setChannel = (kind: (typeof CHANNEL_KINDS)[number], channel: Channel) => {
    if (!prefs.data) return;
    setPrefs.mutate({ ...prefs.data, [kind]: channel });
  };

  const setDigestTime = (value: string) => {
    if (!prefs.data) return;
    setPrefs.mutate({ ...prefs.data, digest_time: value || null });
  };

  return (
    <div className="min-w-0 flex-1 overflow-auto px-4 md:px-8 py-6">
      <h1 className="page-title mb-1 flex items-center gap-2">
        <Icon icon={Bell} size={20} /> Notification settings
      </h1>
      <p className="mb-6 text-sm text-muted">
        <Link to="/inbox" className="underline hover:text-ink">
          Back to Inbox
        </Link>
      </p>

      {prefs.isPending || !prefs.data ? (
        <div className="flex max-w-lg flex-col gap-2" aria-busy>
          {Array.from({ length: 7 }, (_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : (
        <div className="flex max-w-lg flex-col gap-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-2">
                <th className="pb-2 font-medium">Notify me when…</th>
                <th className="pb-2 font-medium">Channel</th>
              </tr>
            </thead>
            <tbody>
              {CHANNEL_KINDS.map((kind) => (
                <tr key={kind} className="border-t border-hair-soft">
                  <td className="py-2 pr-3">{KIND_LABEL[kind]}</td>
                  <td className="py-2">
                    <label className="sr-only" htmlFor={`pref-${kind}`}>
                      {KIND_LABEL[kind]} channel
                    </label>
                    <select
                      id={`pref-${kind}`}
                      value={prefs.data[kind]}
                      onChange={(e) => setChannel(kind, e.target.value as Channel)}
                      className="h-8 rounded-md border border-hair bg-surface px-2 text-sm"
                    >
                      {CHANNEL_OPTIONS.map((c) => (
                        <option key={c} value={c}>
                          {CHANNEL_LABEL[c]}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="border-t border-hair-soft pt-4">
            <label htmlFor="digest-time" className="mb-1 block text-sm font-medium">
              Daily digest time
            </label>
            <p className="mb-2 text-xs text-muted">
              Saved for later — the daily digest itself isn't built yet.
            </p>
            <input
              id="digest-time"
              type="time"
              value={prefs.data.digest_time ?? ''}
              onChange={(e) => setDigestTime(e.target.value)}
              className="h-8 rounded-md border border-hair bg-surface px-2 text-sm"
            />
          </div>
        </div>
      )}
    </div>
  );
}
