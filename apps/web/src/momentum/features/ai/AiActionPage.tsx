import { useParams } from 'react-router';
import { PreviewCard } from './PreviewCard';

/** `/ai/actions/:actionId`: a proposed change on its own page, so a suggestion made elsewhere
 * (an agent, a notification, a link from chat) has a stable place to be reviewed. */
export function AiActionPage() {
  const { actionId } = useParams();
  return (
    <div className="mx-auto w-full max-w-2xl px-6 py-8">
      <h1 className="mb-4 text-lg font-semibold">Suggested changes</h1>
      <PreviewCard actionId={actionId!} />
    </div>
  );
}
