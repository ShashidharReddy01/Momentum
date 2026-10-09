import type { RecordOp } from './queries';

/** Phase 7.6 S76-08 (spec §12.4): the record form is generated from the record type's JSON Schema
 * (pydantic's, with `$defs`) and its display spec (money and date paths, arrays, currency field).
 * Edits are kept as the server's correction operations, applied here too so the form shows them. */

export type FieldKind = 'text' | 'money' | 'number' | 'date' | 'bool' | 'currency';

export interface FieldSpec {
  path: string; // "vendor.name", or a column name inside an array
  label: string;
  kind: FieldKind;
  required: boolean;
}

export interface ArraySpec {
  path: string; // "lines"
  label: string;
  columns: FieldSpec[];
}

export interface FormSpec {
  fields: FieldSpec[];
  arrays: ArraySpec[];
}

type Schema = {
  type?: string | string[];
  title?: string;
  format?: string;
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  anyOf?: Schema[];
  allOf?: Schema[];
  $ref?: string;
  $defs?: Record<string, Schema>;
  default?: unknown;
};

export interface Display {
  money?: string[];
  dates?: string[];
  arrays?: Record<string, string>;
  currency_field?: string | null;
  columns?: string[];
  title?: string;
}

export function humanize(name: string): string {
  const s = name
    .replace(/\[\]|\[\d+\]/g, '')
    .split('.')
    .pop()!
    .replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function resolve(s: Schema | undefined, root: Schema): Schema {
  if (!s) return {};
  if (s.$ref) {
    const name = s.$ref.split('/').pop()!;
    return resolve(root.$defs?.[name], root);
  }
  if (s.allOf?.length === 1) return resolve(s.allOf[0], root);
  if (s.anyOf) {
    const notNull = s.anyOf.filter((x) => x.type !== 'null');
    if (notNull.length === 1) return { ...resolve(notNull[0], root), title: s.title ?? notNull[0]!.title };
  }
  return s;
}

function kindOf(path: string, s: Schema, display: Display): FieldKind {
  const wild = path.replace(/\[\d*\]/g, '[]');
  if ((display.money ?? []).includes(wild)) return 'money';
  if ((display.dates ?? []).includes(wild) || s.format === 'date') return 'date';
  if (display.currency_field && display.currency_field === path) return 'currency';
  const t = Array.isArray(s.type) ? s.type.find((x) => x !== 'null') : s.type;
  if (t === 'boolean') return 'bool';
  if (t === 'number' || t === 'integer') return 'number';
  if (s.anyOf?.some((x) => x.type === 'number')) return 'money';
  return 'text';
}

export function formSpec(schema: Schema, display: Display): FormSpec {
  const fields: FieldSpec[] = [];
  const arrays: ArraySpec[] = [];
  const walk = (obj: Schema, prefix: string) => {
    const req = new Set(obj.required ?? []);
    for (const [name, raw] of Object.entries(obj.properties ?? {})) {
      const s = resolve(raw, schema);
      const path = prefix ? `${prefix}.${name}` : name;
      const t = Array.isArray(s.type) ? s.type.find((x) => x !== 'null') : s.type;
      if (t === 'array') {
        const item = resolve(s.items, schema);
        if (item.properties) {
          const columns: FieldSpec[] = [];
          const ireq = new Set(item.required ?? []);
          for (const [col, craw] of Object.entries(item.properties)) {
            const cs = resolve(craw, schema);
            columns.push({
              path: col,
              label: cs.title ?? humanize(col),
              kind: kindOf(`${path}[].${col}`, cs, display),
              required: ireq.has(col),
            });
          }
          arrays.push({ path, label: display.arrays?.[path] ?? s.title ?? humanize(name), columns });
        }
        continue;
      }
      if (s.properties) {
        walk(s, path);
        continue;
      }
      if (name === 'entity_id' || path.endsWith('.entity_id')) continue; // linked in the entity panel
      fields.push({
        path,
        label: s.title ?? humanize(path),
        kind: kindOf(path, s, display),
        required: req.has(name),
      });
    }
  };
  walk(schema, '');
  return { fields, arrays };
}

// ---------- paths and operations ----------

function segments(path: string): (string | number)[] {
  const out: (string | number)[] = [];
  for (const seg of path.split('.')) {
    const m = /^([a-z_][a-z0-9_]*)(?:\[(\d+)\])?$/.exec(seg);
    if (!m) throw new Error(`Bad path ${path}`);
    out.push(m[1]!);
    if (m[2] !== undefined) out.push(Number(m[2]));
  }
  return out;
}

export function getPath(data: unknown, path: string): unknown {
  let cur: unknown = data;
  for (const s of segments(path)) {
    if (cur == null || typeof cur !== 'object') return undefined;
    cur = (cur as Record<string | number, unknown>)[s];
  }
  return cur;
}

function setPath(data: Record<string, unknown>, path: string, value: unknown): void {
  const segs = segments(path);
  let cur: Record<string | number, unknown> = data;
  segs.forEach((s, i) => {
    if (i === segs.length - 1) {
      cur[s] = value;
      return;
    }
    if (cur[s] == null || typeof cur[s] !== 'object') cur[s] = typeof segs[i + 1] === 'number' ? [] : {};
    cur = cur[s] as Record<string | number, unknown>;
  });
}

/** The data with the operations applied (as the server will). */
export function applyOps(data: Record<string, unknown>, ops: RecordOp[]): Record<string, unknown> {
  const out = structuredClone(data);
  for (const op of ops) {
    if (op.op === 'set') setPath(out, op.path, op.value);
    else if (op.op === 'add_item') {
      const arr = [...((getPath(out, op.array) as unknown[]) ?? [])];
      arr.splice(op.at ?? arr.length, 0, op.item);
      setPath(out, op.array, arr);
    } else if (op.op === 'remove_item') {
      const arr = [...((getPath(out, op.array) as unknown[]) ?? [])];
      arr.splice(op.index, 1);
      setPath(out, op.array, arr);
    } else if (op.op === 'move_item') {
      const arr = [...((getPath(out, op.array) as unknown[]) ?? [])];
      const [item] = arr.splice(op.from, 1);
      arr.splice(op.to, 0, item);
      setPath(out, op.array, arr);
    }
  }
  return out;
}

/** Add an operation; typing into the same field again replaces its last "set". */
export function pushOp(ops: RecordOp[], op: RecordOp): RecordOp[] {
  const last = ops.at(-1);
  if (op.op === 'set' && last?.op === 'set' && last.path === op.path) return [...ops.slice(0, -1), op];
  return [...ops, op];
}

// ---------- money ----------

/** Sum of a money column as exact cents (strings in, a 2-decimal string out). */
export function sumMoney(values: unknown[]): string | null {
  let cents = 0n;
  for (const v of values) {
    const s = String(v ?? '')
      .replace(/,/g, '')
      .trim();
    if (!s) continue;
    const m = /^(-)?(\d+)(?:\.(\d{1,2}))?$/.exec(s);
    if (!m) return null;
    const c = BigInt(m[2]!) * 100n + BigInt((m[3] ?? '').padEnd(2, '0'));
    cents += m[1] ? -c : c;
  }
  const neg = cents < 0n;
  const abs = neg ? -cents : cents;
  return `${neg ? '-' : ''}${abs / 100n}.${String(abs % 100n).padStart(2, '0')}`;
}

// ---------- provenance ----------

export interface Prov {
  method?: string;
  page?: number;
  bbox?: [number, number, number, number];
  text?: string;
  confidence?: number;
}

/** A highlight's text equivalent (spec §12.4): "page 1, top right". */
export function whereOnPage(p: Prov, size?: { width: number; height: number }): string {
  if (!p.page) return 'not located on a page';
  if (!p.bbox || !size) return `page ${p.page}`;
  const [x0, y0, x1, y1] = p.bbox;
  const cx = (x0 + x1) / 2 / size.width;
  const cy = (y0 + y1) / 2 / size.height;
  const v = cy < 1 / 3 ? 'top' : cy < 2 / 3 ? 'middle' : 'bottom';
  const h = cx < 1 / 3 ? 'left' : cx < 2 / 3 ? 'centre' : 'right';
  return `page ${p.page}, ${v === 'middle' && h === 'centre' ? 'middle' : `${v} ${h}`}`;
}
