import { useNavigate, useParams } from 'react-router';
import { useCrumbs } from '@/lib/crumbs';
import { useTaskDetail } from '../detail';
import { TaskPane } from './TaskPane';

/** Full-page task (`/task/:taskId`), e.g. from a copied link. */
export function TaskPage() {
  const { taskId = '' } = useParams();
  const task = useTaskDetail(taskId).data;
  const navigate = useNavigate();
  useCrumbs(task ? [task.project?.name ?? 'Task', task.key] : null);
  return (
    <div className="h-full overflow-auto px-4 md:px-8 py-6">
      <TaskPane taskId={taskId} mode="page" onOpenTask={(id) => navigate(`/task/${id}`)} />
    </div>
  );
}
