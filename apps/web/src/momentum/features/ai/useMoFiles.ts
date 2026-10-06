import { useCallback, useState } from 'react';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';
import type { Screen } from './useMoRuns';

export interface MoFileChip {
  id: string;
  name: string;
  /** `file`: a task or project file (its id goes with each question); `chat`: only in this chat. */
  where: 'file' | 'chat';
}

/**
 * Phase 7.5 (spec §4.8): files put in front of Mo. The paperclip uploads to the task or project
 * on screen when the person may add files there, otherwise to the chat itself (private, deleted
 * with it). A file dragged from the Files tab is just a chip. Nothing is read until a question
 * is sent.
 */
export function useMoFiles(
  base: Screen,
  chat: { conversationId: string | null; adopt: (id: string) => void },
) {
  const api = useApi();
  const [chips, setChips] = useState<MoFileChip[]>([]);
  const [uploading, setUploading] = useState(false);

  const add = useCallback(
    (chip: MoFileChip) => setChips((cs) => (cs.some((c) => c.id === chip.id) ? cs : [...cs, chip])),
    [],
  );
  const remove = useCallback((id: string) => setChips((cs) => cs.filter((c) => c.id !== id)), []);
  const clear = useCallback(() => setChips([]), []);

  const attach = useCallback(
    async (files: File[]) => {
      setUploading(true);
      try {
        for (const file of files) {
          const form = new FormData();
          form.append('file', file);
          let placed: { id: string; filename: string } | null = null;
          try {
            if (base.task_id) {
              placed =
                (
                  await api.POST('/api/v1/tasks/{task_id}/attachments', {
                    params: { path: { task_id: base.task_id } },
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    body: form as any,
                  })
                ).data?.data ?? null;
            } else if (base.project_id) {
              placed =
                (
                  await api.POST('/api/v1/projects/{project_id}/files', {
                    params: { path: { project_id: base.project_id } },
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    body: form as any,
                  })
                ).data?.data ?? null;
            }
          } catch {
            placed = null; // no rights to add files there: keep it in the chat instead
          }
          if (placed) {
            add({ id: placed.id, name: placed.filename, where: 'file' });
            continue;
          }
          const own = new FormData();
          own.append('file', file);
          if (chat.conversationId) own.append('conversation_id', chat.conversationId);
          const res = (
            await api.POST('/api/v1/ai/conversation-files', {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              body: own as any,
            })
          ).data!;
          chat.adopt(res.conversation_id);
          add({ id: res.id, name: res.filename, where: 'chat' });
        }
      } catch (e) {
        toastError(e, "Couldn't attach that file");
      } finally {
        setUploading(false);
      }
    },
    [api, base.task_id, base.project_id, chat, add],
  );

  const fileIds = chips.filter((c) => c.where === 'file').map((c) => c.id);
  return { chips, add, remove, clear, attach, uploading, fileIds };
}
