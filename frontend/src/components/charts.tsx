import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DayRow, Dashboard, GroupRow } from "../api/schemas";
import { fmtDate, fmtDateTime, fmtMoney, fmtPct } from "../lib/format";

type Colors = { gain: string; loss: string; accent: string; muted: string; line: string; panel: string; fg: string };

function readColors(): Colors {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, d: string) => cs.getPropertyValue(n).trim() || d;
  return {
    gain: v("--gain", "#26a69a"),
    loss: v("--loss", "#ef5350"),
    accent: v("--accent", "#60a5fa"),
    muted: v("--muted", "#8b97ad"),
    line: v("--line", "#243049"),
    panel: v("--panel", "#121826"),
    fg: v("--fg", "#e6eaf2"),
  };
}

/** Recharts needs concrete colours; re-read the CSS tokens whenever the theme attribute changes. */
export function useChartColors(): Colors {
  const [c, setC] = useState(readColors);
  useEffect(() => {
    const obs = new MutationObserver(() => setC(readColors()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return c;
}

function TipBox({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-lg">{children}</div>;
}

const axis = (c: Colors) => ({ stroke: c.line, tick: { fill: c.muted, fontSize: 11 }, tickLine: false, axisLine: false });
const num = (v: string) => Number(v);

export function EquityCurve({ data, currency, onSelect }: { data: Dashboard["equity_curve"]; currency: string; onSelect: (tradeId: string) => void }) {
  const c = useChartColors();
  const rows = data.map((p, i) => ({ ...p, i: i + 1, y: num(p.cumulative) }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        onClick={(e) => { const idx = (e as { activeTooltipIndex?: number }).activeTooltipIndex; if (idx !== undefined && rows[Number(idx)]) onSelect(rows[Number(idx)].trade_id); }}>
        <defs>
          <linearGradient id="eq" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={c.accent} stopOpacity={0.3} />
            <stop offset="100%" stopColor={c.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={c.line} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="i" {...axis(c)} />
        <YAxis {...axis(c)} width={70} tickFormatter={(v) => fmtMoney(String(v), currency)} />
        <ReferenceLine y={0} stroke={c.muted} />
        <Tooltip cursor={{ stroke: c.muted }} content={({ active, payload }) => {
          if (!active || !payload?.length) return null;
          const p = payload[0].payload as (typeof rows)[number];
          return (
            <TipBox>
              <div className="font-medium">Trade #{p.i} · {p.symbol}</div>
              <div className="text-muted">{fmtDateTime(p.closed_at)}</div>
              <div>Trade: {fmtMoney(p.net_pnl, currency, { sign: true })}</div>
              <div>Cumulative: {fmtMoney(p.cumulative, currency)}</div>
              <div>Drawdown: {fmtMoney(p.drawdown, currency)}</div>
              <div className="mt-1 text-muted">Click to open the trade</div>
            </TipBox>
          );
        }} />
        <Area isAnimationActive={false} type="monotone" dataKey="y" stroke={c.accent} strokeWidth={2} fill="url(#eq)" dot={false} activeDot={{ r: 5, cursor: "pointer" }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function DailyPnl({ data, currency, onSelect }: { data: DayRow[]; currency: string; onSelect: (date: string) => void }) {
  const c = useChartColors();
  const rows = data.map((d) => ({ ...d, y: num(d.net_pnl) }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={c.line} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="date" {...axis(c)} tickFormatter={(d) => fmtDate(d).replace(/, \d{4}$/, "")} minTickGap={16} />
        <YAxis {...axis(c)} width={70} tickFormatter={(v) => fmtMoney(String(v), currency)} />
        <ReferenceLine y={0} stroke={c.muted} />
        <Tooltip cursor={{ fill: c.line, opacity: 0.4 }} content={({ active, payload }) => {
          if (!active || !payload?.length) return null;
          const d = payload[0].payload as DayRow;
          return (
            <TipBox>
              <div className="font-medium">{fmtDate(d.date)}</div>
              <div>Net: {fmtMoney(d.net_pnl, currency, { sign: true })}</div>
              <div className="text-muted">{d.trades} trades · {d.wins}W / {d.losses}L · fees {fmtMoney(d.fees, currency)}</div>
              <div className="mt-1 text-muted">Click to open this day's trades</div>
            </TipBox>
          );
        }} />
        <Bar isAnimationActive={false} dataKey="y" radius={[4, 4, 0, 0]} cursor="pointer" onClick={(d) => onSelect((d as unknown as DayRow).date)} maxBarSize={28}>
          {rows.map((r) => <Cell key={r.date} fill={r.y >= 0 ? c.gain : c.loss} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function GroupBars({ data, currency, onSelect, height = 240, horizontal = false }: {
  data: GroupRow[]; currency: string; onSelect?: (g: GroupRow) => void; height?: number; horizontal?: boolean;
}) {
  const c = useChartColors();
  const rows = data.map((g) => ({ ...g, y: num(g.net_pnl ?? "0") }));
  const tip = ({ active, payload }: { active?: boolean; payload?: readonly { payload?: unknown }[] }) => {
    if (!active || !payload?.length) return null;
    const g = payload[0].payload as GroupRow;
    return (
      <TipBox>
        <div className="font-medium">{g.label}</div>
        <div>Net: {fmtMoney(g.net_pnl, currency, { sign: true })}</div>
        <div className="text-muted">{g.trades} trades · win rate {fmtPct(g.win_rate)} · expectancy {fmtMoney(g.expectancy, currency)}</div>
        {onSelect && <div className="mt-1 text-muted">Click to drill down</div>}
      </TipBox>
    );
  };
  const bar = (
    <Bar isAnimationActive={false} dataKey="y" radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} cursor={onSelect ? "pointer" : undefined}
      onClick={(d) => onSelect?.(d as unknown as GroupRow)} maxBarSize={28}>
      {rows.map((r, i) => <Cell key={`${r.key}-${i}`} fill={r.y >= 0 ? c.gain : c.loss} />)}
    </Bar>
  );
  return (
    <ResponsiveContainer width="100%" height={height}>
      {horizontal ? (
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
          <CartesianGrid stroke={c.line} strokeDasharray="2 4" horizontal={false} />
          <XAxis type="number" {...axis(c)} tickFormatter={(v) => fmtMoney(String(v), currency)} />
          <YAxis type="category" dataKey="label" {...axis(c)} width={100} />
          <ReferenceLine x={0} stroke={c.muted} />
          <Tooltip cursor={{ fill: c.line, opacity: 0.4 }} content={tip} />
          {bar}
        </BarChart>
      ) : (
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={c.line} strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" {...axis(c)} />
          <YAxis {...axis(c)} width={70} tickFormatter={(v) => fmtMoney(String(v), currency)} />
          <ReferenceLine y={0} stroke={c.muted} />
          <Tooltip cursor={{ fill: c.line, opacity: 0.4 }} content={tip} />
          {bar}
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}

export function Distribution({ data, currency, onSelect }: { data: Dashboard["distribution"]; currency: string; onSelect: (from: string, to: string) => void }) {
  const c = useChartColors();
  const rows = data.buckets.map((b) => ({ ...b, mid: (num(b.from) + num(b.to)) / 2, label: fmtMoney(b.from, currency) }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap={2}>
        <CartesianGrid stroke={c.line} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axis(c)} minTickGap={20} />
        <YAxis {...axis(c)} width={30} allowDecimals={false} />
        <Tooltip cursor={{ fill: c.line, opacity: 0.4 }} content={({ active, payload }) => {
          if (!active || !payload?.length) return null;
          const b = payload[0].payload as (typeof rows)[number];
          return (
            <TipBox>
              <div className="font-medium">{fmtMoney(b.from, currency)} to {fmtMoney(b.to, currency)}</div>
              <div>{b.count} trades ({b.wins} winners)</div>
              <div className="mt-1 text-muted">Click to list these trades</div>
            </TipBox>
          );
        }} />
        <Bar isAnimationActive={false} dataKey="count" radius={[4, 4, 0, 0]} cursor="pointer" onClick={(d) => { const b = d as unknown as (typeof rows)[number]; onSelect(b.from, b.to); }}>
          {rows.map((r) => <Cell key={r.from} fill={r.mid >= 0 ? c.gain : c.loss} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
