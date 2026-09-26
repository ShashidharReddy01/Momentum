import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import {
  useCsvCommit,
  useCsvPreview,
  type CsvColumnMapping,
  type CsvImportResult,
  type CsvPreview,
} from './queries';

const FIELDS = [
  { key: 'title_col', label: 'Title', required: true },
  { key: 'section_col', label: 'Section (optional)', required: false },
  { key: 'assignee_email_col', label: 'Assignee email (optional)', required: false },
  { key: 'due_on_col', label: 'Due date, YYYY-MM-DD (optional)', required: false },
  { key: 'completed_col', label: 'Completed flag (optional)', required: false },
] as const;

/** S2.7.2: upload a CSV → preview headers/sample rows → map columns → import. A missing title
 * in a row is skipped, not an error; sections named in the column are created if they don't
 * already exist in the project. */
export function CsvImportDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [mapping, setMapping] = useState<Partial<CsvColumnMapping>>({});
  const [result, setResult] = useState<CsvImportResult | null>(null);
  const previewM = useCsvPreview();
  const commitM = useCsvCommit();

  const reset = () => {
    setFile(null);
    setPreview(null);
    setMapping({});
    setResult(null);
  };

  const onFile = (f: File | null) => {
    setResult(null);
    setFile(f);
    if (!f) {
      setPreview(null);
      return;
    }
    previewM.mutate(
      { projectId, file: f },
      {
        onSuccess: (p) => {
          setPreview(p);
          const guess = p.headers.find((h) => /title|name/i.test(h));
          setMapping(guess ? { title_col: guess } : {});
        },
      },
    );
  };

  const onImport = () => {
    if (!file || !mapping.title_col) return;
    commitM.mutate(
      { projectId, file, mapping: { ...mapping, title_col: mapping.title_col } },
      { onSuccess: setResult },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) reset();
      }}
      title="Import from CSV"
      className="w-[min(560px,calc(100vw-32px))]"
    >
      <div className="flex flex-col gap-4 p-4">
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />

        {preview ? (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted">
              {preview.row_count} row{preview.row_count === 1 ? '' : 's'} found. Map columns below.
            </p>
            {FIELDS.map((f) => (
              <label key={f.key} className="flex items-center justify-between gap-3 text-sm">
                <span>
                  {f.label}
                  {f.required ? ' *' : ''}
                </span>
                <select
                  value={mapping[f.key] ?? ''}
                  onChange={(e) =>
                    setMapping((m: Partial<CsvColumnMapping>) => ({
                      ...m,
                      [f.key]: e.target.value || undefined,
                    }))
                  }
                  className="h-8 rounded-md border border-hair bg-surface px-2 text-sm"
                >
                  <option value="">{f.required ? 'Select a column…' : "Don't import"}</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr>
                  {preview.headers.map((h) => (
                    <th key={h} className="border-b border-hair-soft px-1 py-1 text-left">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 3).map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} className="truncate px-1 py-1 text-muted">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <Button onClick={onImport} disabled={!mapping.title_col || commitM.isPending} className="w-fit">
              {commitM.isPending ? 'Importing…' : 'Import tasks'}
            </Button>
          </div>
        ) : null}

        {result ? (
          <div className="rounded-md border border-hair bg-surface-2 p-3 text-sm">
            <p className="font-medium">
              Created {result.created}, skipped {result.skipped}
            </p>
            {result.errors.length ? (
              <ul className="mt-1 flex max-h-32 flex-col gap-0.5 overflow-auto text-xs text-muted">
                {result.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
