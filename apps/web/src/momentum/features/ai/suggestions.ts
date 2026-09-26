import type { MoContext } from '@/stores/ui';
import type { Screen } from './useMoRuns';

/** Starter questions for Ask Mo (S3.3.2): about what an "Ask Mo about this" button pinned, else
 * about the screen the user is on. Generic on purpose: they name no seeded data. */
export function suggestionsFor(screen: Screen, context: MoContext | null): string[] {
  const kind = context?.kind ?? (screen.task_id ? 'task' : screen.kind);
  switch (kind) {
    case 'task':
      return ['Summarize this task', "What's left to do here?", 'What is this task waiting on?'];
    case 'selection':
      return ['Summarize these tasks', 'Which of these are at risk?', 'Who is working on these?'];
    case 'project':
      return ["What's blocking this project?", 'What changed this week?', "What's overdue here?"];
    case 'my_tasks':
      return ['What should I work on first?', "What's overdue for me?", 'What is due this week?'];
    case 'inbox':
      return ['What needs my attention?', 'Who is waiting on me?'];
    case 'home':
      return ["What's due today?", "What's overdue across my projects?", 'What should I focus on?'];
    default:
      return ["What's overdue?", 'What changed this week?'];
  }
}

/** The screen an "Ask Mo about this" context stands for (sent with every message). */
export function contextScreen(c: MoContext): Screen {
  if (c.kind === 'task') return { kind: 'task', task_id: c.taskId };
  if (c.kind === 'project') return { kind: 'project', project_id: c.projectId };
  return {
    kind: 'project',
    ...(c.projectId ? { project_id: c.projectId } : {}),
    selected_task_ids: c.taskIds ?? [],
  };
}
