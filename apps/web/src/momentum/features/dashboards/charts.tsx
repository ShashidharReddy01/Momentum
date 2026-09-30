/**
 * The Recharts-drawn widgets (bar, donut, line), in their own lazy chunk (frontend-architecture:
 * charts are lazy). Every colour, line and label comes from our tokens, so both themes read the
 * same; marks follow design-system.md "Charts": bars ≤ 22px with a rounded end, a 2px surface gap
 * between slices, a 2px line with a 10% wash, hairline solid grid, values at the bar tips.
 * Every mark is a button: clicking opens the tasks behind it.
 */
import { useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { cn } from '@/lib/cn';
import {
  bucketLabel,
  colorOf,
  formatAverage,
  formatValue,
  SERIES_COLOR,
  seriesHeadline,
  share,
  unitOf,
} from './model';
import type { GroupRow, QueryResult, QuerySpec, SeriesPoint, WidgetKind } from './queries';
import type { Mark } from './WidgetCard';

const AXIS = { fill: 'var(--muted)', fontSize: 12 };
const BAR_ROW = 34;

export default function Chart({
  kind,
  spec,
  data,
  onDrill,
}: {
  kind: WidgetKind;
  spec: QuerySpec;
  data: QueryResult;
  onDrill: (mark: Mark) => void;
}) {
  if (kind === 'donut') return <Donut spec={spec} data={data} onDrill={onDrill} />;
  if (kind === 'line') return <Trend spec={spec} data={data} onDrill={onDrill} />;
  return <Bars spec={spec} data={data} onDrill={onDrill} />;
}

function Tip({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="rounded-md bg-surface px-2.5 py-1.5 text-xs shadow-pop">
      <p className="font-medium text-ink">{title}</p>
      {lines.map((l) => (
        <p key={l} className="text-muted">
          {l}
        </p>
      ))}
      <p className="mt-0.5 text-muted-2">Click to see the tasks</p>
    </div>
  );
}

// ---------- bars: horizontal, so every label reads in full ----------

function Bars({ spec, data, onDrill }: { spec: QuerySpec; data: QueryResult; onDrill: (m: Mark) => void }) {
  const rows = (data.groups ?? []).map((g, i) => ({ ...g, fill: colorOf(spec, g, i, 'bar') }));
  const longest = Math.max(...rows.map((r) => r.label.length), 4);
  const labelWidth = Math.min(180, 16 + longest * 7);
  const height = rows.length * BAR_ROW + 8;
  return (
    <div
      style={{ height }}
      role="img"
      aria-label={`${data.description}: ${rows.map((r) => `${r.label} ${formatValue(data, r.value)}`).join(', ')}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 0, right: 48, bottom: 0, left: 0 }}
          barCategoryGap={6}
        >
          <XAxis type="number" hide domain={[0, 'dataMax']} />
          <YAxis
            type="category"
            dataKey="label"
            width={labelWidth}
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            interval={0}
            tickFormatter={(v: string) => (v.length > 26 ? `${v.slice(0, 25)}…` : v)}
          />
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            isAnimationActive={false}
            content={({ active, payload }) => {
              const g = active ? (payload?.[0]?.payload as GroupRow | undefined) : undefined;
              if (!g) return null;
              return (
                <Tip
                  title={g.label}
                  lines={[
                    `${formatValue(data, g.value)} ${unitOf(data, g.value)}`,
                    `${share(g.value, data.total)} of ${formatValue(data, data.total)}`,
                  ]}
                />
              );
            }}
          />
          <Bar
            dataKey="value"
            radius={[0, 4, 4, 0]}
            maxBarSize={22}
            cursor="pointer"
            isAnimationActive={false}
            onClick={(entry) => {
              const g = (entry as { payload?: GroupRow }).payload;
              if (g) onDrill({ key: g.key, label: g.label });
            }}
          >
            {rows.map((r) => (
              <Cell key={r.key} fill={r.fill} />
            ))}
            <LabelList
              dataKey="value"
              position="right"
              formatter={(v: unknown) => formatValue(data, Number(v))}
              style={{ fill: 'var(--ink-2)', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------- donut: the total in the middle, a legend that is also the table ----------

function Donut({ spec, data, onDrill }: { spec: QuerySpec; data: QueryResult; onDrill: (m: Mark) => void }) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = (data.groups ?? []).map((g, i) => ({ ...g, fill: colorOf(spec, g, i, 'donut') }));
  const sum = rows.reduce((a, r) => a + r.value, 0);
  const focus = rows.find((r) => r.key === hover);
  return (
    <div className="flex flex-wrap items-center justify-center gap-4">
      <div className="relative h-44 w-44 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={rows}
              dataKey="value"
              nameKey="label"
              innerRadius="64%"
              outerRadius="100%"
              startAngle={90}
              endAngle={-270}
              stroke="var(--surface)"
              strokeWidth={2}
              isAnimationActive={false}
              cursor="pointer"
              onMouseEnter={(_, i) => setHover(rows[i]?.key ?? null)}
              onMouseLeave={() => setHover(null)}
              onClick={(_, i) => {
                const g = rows[i];
                if (g) onDrill({ key: g.key, label: g.label });
              }}
            >
              {rows.map((r) => (
                <Cell key={r.key} fill={r.fill} opacity={hover && hover !== r.key ? 0.35 : 1} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="text-2xl font-semibold">{formatValue(data, focus ? focus.value : sum)}</span>
          <span className="max-w-24 truncate text-xs text-muted">
            {focus ? focus.label : unitOf(data, sum)}
          </span>
        </div>
      </div>
      <ul className="min-w-48 flex-1 space-y-0.5">
        {rows.map((r) => (
          <li key={r.key}>
            <button
              type="button"
              onClick={() => onDrill({ key: r.key, label: r.label })}
              onMouseEnter={() => setHover(r.key)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(r.key)}
              onBlur={() => setHover(null)}
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-sm hover:bg-surface-2',
                hover === r.key && 'bg-surface-2',
              )}
            >
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: r.fill }} />
              <span className="min-w-0 flex-1 truncate">{r.label}</span>
              <span className="tabular-nums font-medium">{formatValue(data, r.value)}</span>
              <span className="w-10 text-right tabular-nums text-xs text-muted">{share(r.value, sum)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- trend: a line with a wash, the latest bucket against the average ----------

function Trend({ spec, data, onDrill }: { spec: QuerySpec; data: QueryResult; onDrill: (m: Mark) => void }) {
  const points = data.series ?? [];
  const { latest, average } = seriesHeadline(points);
  const bucket = spec.time_bucket ?? 'week';
  const rows = points.map((p) => ({ ...p, label: bucketLabel(p.start, bucket) }));
  const empty = points.every((p) => p.value === 0);
  const now = spec.time_field === 'due' ? 'first' : 'this';
  const pick = (index: unknown) => {
    const i = typeof index === 'number' ? index : Number(index);
    const p = Number.isFinite(i) ? points[i] : undefined;
    if (p) onDrill({ bucketStart: p.start, label: bucketLabel(p.start, bucket) });
  };
  return (
    <div>
      <p className="mb-2 flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="text-xl font-semibold">
          {formatValue(data, spec.time_field === 'due' ? (points[0]?.value ?? 0) : latest)}
        </span>
        <span className="text-muted">
          {now} {bucket}
          {average !== null && spec.time_field !== 'due'
            ? ` · average ${formatAverage(data, average)} per ${bucket} before`
            : ''}
        </span>
      </p>
      {empty ? <p className="mb-1 text-xs text-muted">Nothing in this period yet.</p> : null}
      <div
        className="h-44"
        role="img"
        aria-label={`${data.description}: ${rows.map((r) => `${r.label} ${formatValue(data, r.value)}`).join(', ')}`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={rows}
            margin={{ top: 6, right: 20, bottom: 0, left: -18 }}
            onClick={(state) => pick((state as { activeTooltipIndex?: unknown } | null)?.activeTooltipIndex)}
          >
            <CartesianGrid vertical={false} stroke="var(--hair-soft)" />
            <XAxis
              dataKey="label"
              tick={AXIS}
              tickLine={false}
              axisLine={{ stroke: 'var(--hairline)' }}
              minTickGap={16}
            />
            <YAxis
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              allowDecimals={data.measure === 'sum_estimate'}
              width={48}
              tickFormatter={(v: number) => formatValue(data, v)}
            />
            <Tooltip
              cursor={{ stroke: 'var(--muted-2)', strokeWidth: 1 }}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const p = active
                  ? (payload?.[0]?.payload as (SeriesPoint & { label: string }) | undefined)
                  : undefined;
                if (!p) return null;
                const span = p.start === p.end ? p.label : `${p.label} – ${bucketLabel(p.end, 'day')}`;
                return (
                  <Tip title={span} lines={[`${formatValue(data, p.value)} ${unitOf(data, p.value)}`]} />
                );
              }}
            />
            <Area
              type="linear"
              dataKey="value"
              stroke={SERIES_COLOR}
              strokeWidth={2}
              fill={SERIES_COLOR}
              fillOpacity={0.1}
              isAnimationActive={false}
              dot={false}
              activeDot={{
                r: 5,
                stroke: 'var(--surface)',
                strokeWidth: 2,
                fill: SERIES_COLOR,
                cursor: 'pointer',
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
