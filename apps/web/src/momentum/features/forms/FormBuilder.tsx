import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { useProjectFields } from '@/features/fields';
import { useSections } from '@/features/sections';
import { FIXED_TARGETS, MAX_QUESTIONS, newQuestionId, questionsValid } from './formMeta';
import type { FormOut, FormSpec, Question } from './queries';

const selectClass =
  'h-8 rounded-md border border-hairline bg-surface-2 px-2.5 text-sm focus:border-focus focus:outline-none';

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`h-5 w-9 shrink-0 rounded-full transition-colors ${checked ? 'bg-accent' : 'bg-hairline'}`}
    >
      <span
        className={`block h-4 w-4 rounded-full bg-surface shadow transition-transform ${checked ? 'translate-x-4' : 'translate-x-0.5'}`}
      />
    </button>
  );
}

function QuestionRow({
  question,
  index,
  earlier,
  targetOptions,
  onChange,
  onRemove,
  removable,
}: {
  question: Question;
  index: number;
  earlier: Question[];
  targetOptions: { id: string; label: string }[];
  onChange: (q: Question) => void;
  onRemove: () => void;
  removable: boolean;
}) {
  const isTitle = question.maps_to === 'title';
  return (
    <li className="flex flex-col gap-1.5 rounded-md border border-hair-soft p-2.5">
      <div className="flex items-center gap-1.5">
        <span className="w-4 shrink-0 text-xs text-muted-2">{index + 1}.</span>
        <Input
          aria-label={`Question ${index + 1} label`}
          value={question.label}
          onChange={(e) => onChange({ ...question, label: e.target.value })}
          placeholder="Question"
          className="min-w-0 flex-1"
          maxLength={200}
        />
        <select
          aria-label={`Question ${index + 1} maps to`}
          value={question.maps_to}
          disabled={isTitle}
          onChange={(e) => onChange({ ...question, maps_to: e.target.value })}
          className={selectClass}
        >
          {targetOptions.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-xs text-muted">
          <input
            type="checkbox"
            checked={question.required}
            disabled={isTitle}
            onChange={(e) => onChange({ ...question, required: e.target.checked })}
          />
          Required
        </label>
        {removable ? (
          <IconButton
            icon={Trash2}
            label={`Remove question ${index + 1}`}
            size="icon-sm"
            onClick={onRemove}
          />
        ) : null}
      </div>
      {earlier.length > 0 && !isTitle ? (
        <div className="flex items-center gap-1.5 pl-6 text-xs text-muted">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={!!question.show_if}
              onChange={(e) =>
                onChange({
                  ...question,
                  show_if: e.target.checked ? { question_id: earlier[0]!.id, equals: '' } : null,
                })
              }
            />
            Only show if
          </label>
          {question.show_if ? (
            <>
              <select
                aria-label={`Question ${index + 1} depends on`}
                value={question.show_if.question_id}
                onChange={(e) =>
                  onChange({ ...question, show_if: { ...question.show_if!, question_id: e.target.value } })
                }
                className={selectClass}
              >
                {earlier.map((q) => (
                  <option key={q.id} value={q.id}>
                    {q.label || q.id}
                  </option>
                ))}
              </select>
              <span>equals</span>
              <Input
                aria-label={`Question ${index + 1} depends-on value`}
                value={String(question.show_if.equals ?? '')}
                onChange={(e) =>
                  onChange({ ...question, show_if: { ...question.show_if!, equals: e.target.value } })
                }
                className="h-7 w-32"
              />
            </>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/** Create/edit a form: title/description/section, the question list (each mapped to the task
 * title/description/assignee/due date/priority or a custom field), and whether it's enabled and
 * public. Branching v1: a question can be shown only when an earlier one's answer equals a
 * value. Mirrors `RuleBuilder`'s shape. */
export function FormBuilder({
  projectId,
  initial,
  saving,
  onCancel,
  onSave,
}: {
  projectId: string;
  initial?: FormOut;
  saving: boolean;
  onCancel: () => void;
  onSave: (spec: FormSpec) => void;
}) {
  const sections = useSections(projectId);
  const projectFields = useProjectFields(projectId);
  const fieldTargets = (projectFields.data ?? [])
    .filter((pf) => pf.field.type !== 'people')
    .map((pf) => ({ id: pf.field.id, label: pf.field.name }));
  const targetOptions = [...FIXED_TARGETS, ...fieldTargets];

  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [sectionId, setSectionId] = useState(initial?.section_id ?? '');
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [publicEnabled, setPublicEnabled] = useState(initial?.public_enabled ?? false);
  const [conversational, setConversational] = useState(initial?.conversational ?? false);
  const [questions, setQuestions] = useState<Question[]>(
    initial?.questions ?? [{ id: 'q1', label: 'What needs to be done?', required: true, maps_to: 'title' }],
  );

  const setQuestion = (i: number, q: Question) =>
    setQuestions((qs) => qs.map((existing, idx) => (idx === i ? q : existing)));
  const addQuestion = () =>
    setQuestions((qs) => [
      ...qs,
      { id: newQuestionId(qs), label: '', required: false, maps_to: 'description' },
    ]);
  const removeQuestion = (i: number) => setQuestions((qs) => qs.filter((_q, idx) => idx !== i));

  const canSave = !!name.trim() && questionsValid(questions);

  return (
    <div className="flex flex-col gap-2.5 p-3">
      <Input
        aria-label="Form name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Form name"
        maxLength={200}
      />
      <textarea
        aria-label="Form description"
        value={description ?? ''}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Shown above the questions (optional)"
        maxLength={2000}
        rows={2}
        className="w-full rounded-md border border-hairline bg-surface-2 px-2.5 py-1.5 text-sm placeholder:text-muted-2 focus:border-focus focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-sm text-muted">
          Section
          <select
            aria-label="Section new tasks are created in"
            value={sectionId}
            onChange={(e) => setSectionId(e.target.value)}
            className={selectClass}
          >
            <option value="">Default section</option>
            {(sections.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <span className="flex items-center gap-1.5 text-sm text-muted">
          <Toggle checked={enabled} onChange={setEnabled} label="Accepting submissions" />
          Accepting submissions
        </span>
        <span className="flex items-center gap-1.5 text-sm text-muted">
          <Toggle checked={publicEnabled} onChange={setPublicEnabled} label="Public link" />
          Public link (no login)
        </span>
        <span className="flex items-center gap-1.5 text-sm text-muted">
          <Toggle checked={conversational} onChange={setConversational} label="Conversational" />
          Conversational (Mo asks the questions in a chat)
        </span>
      </div>

      <ul className="flex flex-col gap-2">
        {questions.map((q, i) => (
          <QuestionRow
            key={q.id}
            question={q}
            index={i}
            earlier={questions.slice(0, i)}
            targetOptions={targetOptions}
            onChange={(next) => setQuestion(i, next)}
            onRemove={() => removeQuestion(i)}
            removable={q.maps_to !== 'title'}
          />
        ))}
      </ul>
      {questions.length < MAX_QUESTIONS ? (
        <Button size="sm" variant="ghost" className="justify-start" onClick={addQuestion}>
          <Icon icon={Plus} /> Add question
        </Button>
      ) : null}

      <div className="flex justify-end gap-2 pt-1">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          size="sm"
          loading={saving}
          disabled={!canSave}
          onClick={() =>
            onSave({
              name: name.trim(),
              description: description.trim() || null,
              section_id: sectionId || null,
              questions,
              enabled,
              public_enabled: publicEnabled,
              conversational,
            })
          }
        >
          {initial ? 'Save form' : 'Create form'}
        </Button>
      </div>
    </div>
  );
}
