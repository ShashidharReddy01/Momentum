import { MessagesSquare, SquarePen } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { AICallout } from '@/components/common/AI';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { useUi } from '@/stores/ui';
import { MoComposer, MoThread } from './MoThread';
import { useConversation, useConversations } from './queries';
import { runsFromMessages, useMoRuns } from './useMoRuns';

/**
 * `/ask` and `/ask/:conversationId` (S3.3.1): Ask Mo full page — my past conversations on the
 * left, the open one on the right. A new question here starts a conversation and the URL follows
 * it, so it can be reopened later (also from the panel's "Open chats page").
 */
export function AskPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const openPalette = useUi((s) => s.openPalette);
  const list = useConversations();
  const stored = useConversation(conversationId);
  const mo = useMoRuns();
  const { open, newChat } = mo;
  const end = useRef<HTMLDivElement>(null);
  const busy = mo.runs.some((r) => r.status === 'running');

  // opening a stored conversation (not the one this page just started: it's already shown);
  // leaving one for plain /ask ("New chat") starts afresh
  const prevParam = useRef(conversationId);
  useEffect(() => {
    const prev = prevParam.current;
    prevParam.current = conversationId;
    if (!conversationId) {
      if (prev) newChat();
      return;
    }
    if (conversationId === mo.conversationId || !stored.data) return;
    open(conversationId, runsFromMessages(stored.data.messages));
  }, [conversationId, stored.data, mo.conversationId, open, newChat]);
  // a question asked on a new chat: the URL follows the conversation the server created
  useEffect(() => {
    if (mo.conversationId && mo.conversationId !== conversationId)
      navigate(`/ask/${mo.conversationId}`, { replace: true });
    // only when the hook's conversation changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mo.conversationId]);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [mo.runs]);

  const title = list.data?.find((c) => c.id === conversationId)?.title;

  return (
    <div className="flex h-full min-h-0">
      <nav
        aria-label="Conversations"
        className="flex w-64 shrink-0 flex-col border-r border-hair-soft max-md:hidden"
      >
        <div className="flex items-center justify-between px-4 py-3">
          <h1 className="page-title text-[17px]">Ask Mo</h1>
          <Button size="sm" variant="ghost" onClick={() => navigate('/ask')} disabled={busy}>
            <SquarePen size={14} aria-hidden /> New chat
          </Button>
        </div>
        <ul className="flex-1 overflow-auto px-2 pb-3">
          {list.isPending ? (
            <li className="space-y-2 p-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-32" />
            </li>
          ) : null}
          {list.data?.length === 0 ? (
            <li className="px-2 py-1 text-sm text-muted">No conversations yet.</li>
          ) : null}
          {list.data?.map((c) => (
            <li key={c.id}>
              <Link
                to={`/ask/${c.id}`}
                aria-current={c.id === conversationId ? 'page' : undefined}
                className={cn(
                  'block truncate rounded-md px-2 py-1.5 text-sm text-ink-2 hover:bg-surface-2',
                  c.id === conversationId && 'bg-surface-2 font-medium text-ink',
                )}
              >
                {c.title}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <section aria-label={title ?? 'New chat'} className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 space-y-5 overflow-auto px-4 py-6 md:px-8">
          <div className="mx-auto max-w-2xl space-y-5">
            {conversationId && stored.isError ? (
              <ErrorState error={stored.error} onRetry={() => void stored.refetch()} />
            ) : null}
            {conversationId && stored.isPending && !mo.runs.length ? (
              <Skeleton className="h-16 w-full" />
            ) : null}
            {!conversationId && !mo.runs.length ? (
              <EmptyState icon={MessagesSquare} title="Ask Mo about your work">
                Answers come from your workspace, with links to the tasks and projects Mo used.
              </EmptyState>
            ) : null}
            {!conversationId && !mo.runs.length ? (
              <AICallout>
                Try “what&apos;s blocking launch?”, “what did we decide about pricing?”, or “what&apos;s
                overdue in Website Revamp?”
              </AICallout>
            ) : null}
            <MoThread
              runs={mo.runs}
              onEdit={(r) => openPalette(r.text)}
              onChoose={(_r, choice) => void mo.ask(choice)}
              onRated={(r, rating) => mo.rate(r.id, rating)}
            />
            <div ref={end} />
          </div>
        </div>
        <div className="mx-auto w-full max-w-2xl">
          <MoComposer onSend={(text) => void mo.ask(text)} busy={busy} />
        </div>
      </section>
    </div>
  );
}
