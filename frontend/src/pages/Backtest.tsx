import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "../api/client";
import { useBacktestBars, useBacktestResults, useBacktests, useBacktestState, useMarketDataInfo } from "../api/hooks";
import * as s from "../api/schemas";
import { CandleChart, type ChartMarker, type PriceLine } from "../components/CandleChart";
import { EquityCurve } from "../components/charts";
import { Badge, Button, Empty, ErrorState, Field, Input, Loading, Panel, Select, errorMessage } from "../components/ui";
import { fmtDateTime, fmtMoney, fmtNum, fmtPct, fmtR, fmtRatio, pnlClass, trimDecimal } from "../lib/format";
import { SPEEDS, initialReplayState, replayReducer, tickPlan } from "../lib/replayMachine";

const decimal = /^\d+(\.\d+)?$/;

export function BacktestListPage() {
  const list = useBacktests();
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Backtesting</h1>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Sessions" className="xl:col-span-2">
          {list.isLoading ? <Loading /> : list.isError ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> :
            list.data!.length === 0 ? <Empty title="No backtests yet">Pick a pair and a date range, then trade it bar by bar without seeing what comes next.</Empty> : (
              <ul className="divide-y divide-line" data-testid="backtest-list">
                {list.data!.map((b) => (
                  <li key={b.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                    <Badge tone={b.status === "completed" ? "muted" : "accent"}>{b.status}</Badge>
                    <Link className="font-medium hover:text-accent" to={`/backtest/${b.id}`}>{b.title}</Link>
                    <span className="text-xs text-muted">{b.closed_trades} trades · {Math.round(b.progress * 100)}%</span>
                    <span className={`num ml-auto ${pnlClass(b.net_pnl)}`}>{fmtMoney(b.net_pnl, b.currency, { sign: true })}</span>
                  </li>
                ))}
              </ul>
            )}
        </Panel>
        <Panel title="New backtest"><NewBacktest /></Panel>
      </div>
    </div>
  );
}

const newForm = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Choose a start date"),
  balance: z.string().regex(decimal, "Enter a positive amount").refine((v) => Number(v) > 0, "Enter a positive amount"),
  commission: z.string().regex(decimal, "Enter 0 or more"),
  slippage: z.string().regex(decimal, "Enter 0 or more"),
});

export function NewBacktest() {
  const info = useMarketDataInfo();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [yesterday] = useState(() => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10));
  const [f, setF] = useState({ symbol: "EURUSD", timeframe: "5m", date: yesterday, days: "1", balance: "10000", commission: "3.50", slippage: "0.2" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/backtests", { method: "POST", body, schema: s.backtestSession }),
    onSuccess: (b) => { qc.invalidateQueries({ queryKey: ["backtests"] }); nav(`/backtest/${b.id}`); },
  });
  if (info.isLoading) return <Loading />;
  if (info.isError) return <ErrorState error={info.error} />;
  if (!info.data?.enabled) return <p className="text-sm text-muted">Historical market data is disabled on this server.</p>;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const r = newForm.safeParse(f);
    const errs: Record<string, string> = {};
    if (!r.success) for (const i of r.error.issues) errs[String(i.path[0])] = i.message;
    const start = new Date(`${f.date}T00:00:00Z`);
    const end = new Date(start.getTime() + Number(f.days) * 86_400_000);
    if (!errs.date && end.toISOString().slice(0, 10) > new Date().toISOString().slice(0, 10)) errs.date = "The session must end by today (UTC)";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    create.mutate({
      symbol: f.symbol, timeframe: f.timeframe, start_at: start.toISOString(), end_at: end.toISOString(),
      starting_balance: f.balance, commission_per_100k: f.commission, slippage_pips: f.slippage,
    });
  };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-3" onSubmit={submit} aria-label="New backtest" noValidate>
      <p className="text-xs text-muted">Simulated trades are kept apart from your real journal. Bars are revealed by the server, so you can't peek ahead.</p>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Symbol"><Select className="w-full" value={f.symbol} onChange={set("symbol")}>{(info.data.symbols ?? []).map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Timeframe"><Select className="w-full" value={f.timeframe} onChange={set("timeframe")}>{info.data.timeframes.map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Start date (UTC)" error={errors.date}><Input type="date" value={f.date} max={yesterday} onChange={set("date")} /></Field>
        <Field label="Days"><Select className="w-full" value={f.days} onChange={set("days")}>{["1", "2", "3", "5", "10"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Starting balance" error={errors.balance} hint="in the pair's quote currency"><Input inputMode="decimal" value={f.balance} onChange={set("balance")} /></Field>
        <Field label="Commission per 100k" error={errors.commission} hint="per side"><Input inputMode="decimal" value={f.commission} onChange={set("commission")} /></Field>
        <Field label="Slippage (pips)" error={errors.slippage} hint="on market and stop fills"><Input inputMode="decimal" value={f.slippage} onChange={set("slippage")} /></Field>
      </div>
      {create.isError && <p className="text-xs text-loss" role="alert">{errorMessage(create.error)}</p>}
      <Button type="submit" disabled={create.isPending}>{create.isPending ? "Preparing data…" : "Start backtest"}</Button>
    </form>
  );
}

export function BacktestPage() {
  const { id = "" } = useParams();
  const bars = useBacktestBars(id);
  const st = useBacktestState(id);
  if (bars.isLoading || st.isLoading) return <Loading label="Loading backtest…" />;
  if (bars.isError) return <ErrorState error={bars.error} onRetry={() => bars.refetch()} />;
  if (st.isError) return <ErrorState error={st.error} onRetry={() => st.refetch()} />;
  if (bars.data!.status === "pending") return <Loading label={`Downloading ${bars.data!.provider.display_name} data for ${bars.data!.coverage.pending_days.length} day(s)…`} />;
  return <SessionView key={id} initialBars={bars.data!.bars} state={st.data!} />;
}

function SessionView({ initialBars, state }: { initialBars: s.Bar[]; state: s.BacktestState }) {
  const b = state.session;
  const id = b.id;
  const qc = useQueryClient();
  const [bars, setBars] = useState(initialBars);
  const [speed, setSpeed] = useState(b.speed);
  const [machine, dispatch] = useReducer(replayReducer, initialReplayState);
  const [lastEvent, setLastEvent] = useState<string | null>(null);
  const busy = useRef(false);
  const finished = b.status === "completed";
  const results = useBacktestResults(id, true);

  useEffect(() => dispatch({ type: "LOADED", completed: b.at_end || finished }), [b.at_end, finished]);

  const apply = useCallback((r: s.BacktestState) => {
    qc.setQueryData(["backtest", id], r);
    if (r.bars?.length) setBars((prev) => [...prev, ...r.bars!]);
    if (r.events && r.events.fills) setLastEvent(`${r.events.fills} fill(s)${r.events.ambiguous ? `, ${r.events.ambiguous} ambiguous` : ""}`);
    qc.invalidateQueries({ queryKey: ["backtest-results", id] });
    qc.invalidateQueries({ queryKey: ["backtests"] });
  }, [qc, id]);

  const tick = useCallback(async (n: number) => {
    if (busy.current) return;
    busy.current = true;
    try {
      const r = await api(`/backtests/${id}/advance`, { method: "POST", body: { steps: n }, schema: s.backtestState });
      apply(r);
      // Stop playing when an order fills, so the trader sees it.
      const completed = r.session.at_end;
      dispatch({ type: "STEP_DONE", completed });
      if (!completed && r.events?.fills) dispatch({ type: "PAUSE" });
    } catch (e) {
      dispatch({ type: "FAIL", message: errorMessage(e) });
    } finally {
      busy.current = false;
    }
  }, [id, apply]);

  useEffect(() => {
    if (machine.status !== "playing") return;
    const plan = tickPlan(speed);
    const h = setInterval(() => void tick(plan.steps), plan.intervalMs);
    return () => clearInterval(h);
  }, [machine.status, speed, tick]);

  const markers: ChartMarker[] = state.fills.map((f) => ({
    t: f.t - (f.t % (bars.length > 1 ? bars[1].t - bars[0].t : 60)), kind: f.side,
    text: `${f.side === "buy" ? "B" : "S"} ${trimDecimal(f.quantity)} @ ${trimDecimal(f.price)}${f.ambiguous ? " ?" : ""}`,
  }));
  const lines: PriceLine[] = state.orders.filter((o) => o.status === "pending" && o.price).map((o) => ({
    price: o.price!, label: o.kind === "entry" ? `${o.side} ${o.type}` : o.kind === "stop_loss" ? "stop" : "target",
    tone: o.kind === "stop_loss" ? "loss" : o.kind === "take_profit" ? "gain" : "accent",
  }));
  const playing = machine.status === "playing";
  const canTrade = !finished && !b.at_end;

  return (
    <div className="space-y-4">
      <Link to="/backtest" className="text-xs text-muted hover:text-fg">← Backtests</Link>
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{b.title}</h1>
        <Badge tone="warn">simulated</Badge>
        <Badge>{b.symbol} · {b.timeframe}</Badge>
        {finished && <Badge>finished</Badge>}
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Chart" className="xl:col-span-2">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Button variant="ghost" disabled={!canTrade || playing} onClick={() => void tick(1)}>Step</Button>
            <Button variant="ghost" disabled={!canTrade || playing} onClick={() => void tick(10)}>Step 10</Button>
            <Button disabled={!canTrade} onClick={() => dispatch({ type: playing ? "PAUSE" : "PLAY" })}>{playing ? "Pause" : "Play"}</Button>
            <Select aria-label="Speed" value={speed} onChange={(e) => { const v = Number(e.target.value); setSpeed(v); void api(`/backtests/${id}`, { method: "PATCH", body: { speed: v } }).catch(() => undefined); }}>
              {SPEEDS.map((x) => <option key={x} value={x}>{x} bar/s</option>)}
            </Select>
            <span className="text-xs text-muted" data-testid="backtest-state">{finished ? "finished" : machine.status}</span>
            <span className="ml-auto text-xs text-muted">{fmtDateTime(b.cursor_at)} · {Math.round(b.progress * 100)}%</span>
          </div>
          {machine.status === "error" && <p role="alert" className="mb-2 text-xs text-loss">{machine.message} <button className="underline" onClick={() => dispatch({ type: "RETRY" })}>Retry</button></p>}
          <CandleChart bars={bars} timeframe={b.timeframe} markers={markers} priceLines={lines} follow testId="backtest-chart" />
          <p className="mt-2 text-xs text-muted">
            {lastEvent ? `Last step: ${lastEvent}. ` : ""}Fills use 1-minute bid/ask candles; "?" marks a fill whose order inside its minute is unknown.
          </p>
        </Panel>
        <div className="space-y-4">
          <Panel title="Account"><AccountPanel state={state} results={results.data} /></Panel>
          {canTrade && <Panel title="Order ticket"><OrderTicket state={state} onDone={apply} /></Panel>}
          {!finished && <FinishPanel id={id} hasPosition={Number(state.position) !== 0} onDone={apply} />}
        </div>
      </div>
      <Panel title="Orders"><OrdersTable state={state} onDone={apply} canCancel={canTrade} /></Panel>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Fills"><FillsTable state={state} /></Panel>
        <Panel title="Simulated trades"><TradesTable trades={state.trades} currency={b.currency} /></Panel>
      </div>
      {finished && <ResultsPanel id={id} results={results} />}
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Session notes"><Notes session={b} /></Panel>
        <Panel title="Screenshots"><Screenshots id={id} /></Panel>
      </div>
      <Panel title="Simulation configuration">
        <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[max-content_1fr]">
          {Object.entries(b.config).map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd>{String(v)}</dd></div>)}
        </dl>
      </Panel>
    </div>
  );
}

function AccountPanel({ state, results }: { state: s.BacktestState; results?: s.BacktestResults }) {
  const c = state.session.currency;
  const pos = Number(state.position);
  return (
    <dl className="grid grid-cols-2 gap-2 text-sm" data-testid="backtest-account">
      <div><dt className="text-xs text-muted">Balance</dt><dd className="num">{results ? fmtMoney(results.balance, c) : "…"}</dd></div>
      <div><dt className="text-xs text-muted">Realized net</dt><dd className={`num ${pnlClass(results?.realized_net_pnl)}`}>{results ? fmtMoney(results.realized_net_pnl, c, { sign: true }) : "…"}</dd></div>
      <div><dt className="text-xs text-muted">Position</dt><dd className="num">{pos === 0 ? "flat" : `${pos > 0 ? "long" : "short"} ${fmtNum(String(Math.abs(pos)), 0)}`}</dd></div>
      <div><dt className="text-xs text-muted">Open P&L (gross)</dt><dd className={`num ${pnlClass(state.open_pnl)}`}>{state.open_pnl ? fmtMoney(state.open_pnl, c, { sign: true }) : "—"}</dd></div>
      <div className="col-span-2 text-xs text-muted">{state.quote ? `Last bid ${trimDecimal(state.quote.bid)} · ask ${trimDecimal(state.quote.ask)}` : "No price revealed yet"}</div>
    </dl>
  );
}

const ticket = z.object({
  size: z.string().regex(decimal, "Enter a positive number").refine((v) => Number(v) > 0, "Enter a positive number"),
  price: z.string().refine((v) => v === "" || decimal.test(v), "Enter a price"),
  stop: z.string().refine((v) => v === "" || decimal.test(v), "Enter a price"),
  target: z.string().refine((v) => v === "" || decimal.test(v), "Enter a price"),
});

export function OrderTicket({ state, onDone }: { state: s.BacktestState; onDone: (r: s.BacktestState) => void }) {
  const [f, setF] = useState({ type: "market", sizing: "quantity", size: "10000", price: "", stop: "", target: "", note: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const place = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/backtests/${state.session.id}/orders`, { method: "POST", body, schema: s.backtestState }),
    onSuccess: (r) => { onDone(r); setF((x) => ({ ...x, price: "", note: "" })); },
  });
  const submit = (side: "buy" | "sell") => {
    const r = ticket.safeParse(f);
    const errs: Record<string, string> = {};
    if (!r.success) for (const i of r.error.issues) errs[String(i.path[0])] = i.message;
    if (f.type !== "market" && !f.price) errs.price = "Limit and stop orders need a price";
    if (f.sizing === "risk" && !f.stop) errs.stop = "Sizing by risk needs a stop-loss";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    place.mutate({
      side, type: f.type, ...(f.sizing === "quantity" ? { quantity: f.size } : { risk_amount: f.size }),
      price: f.type === "market" ? null : f.price, stop_loss: f.stop || null, take_profit: f.target || null, note: f.note || null,
    });
  };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-2" aria-label="Order ticket" noValidate onSubmit={(e) => e.preventDefault()}>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Order type"><Select className="w-full" value={f.type} onChange={set("type")}><option value="market">Market (next open)</option><option value="limit">Limit</option><option value="stop">Stop</option></Select></Field>
        <Field label="Price" error={errors.price}><Input inputMode="decimal" value={f.price} onChange={set("price")} disabled={f.type === "market"} /></Field>
        <Field label="Size by"><Select className="w-full" value={f.sizing} onChange={set("sizing")}><option value="quantity">Units</option><option value="risk">Risk amount</option></Select></Field>
        <Field label={f.sizing === "quantity" ? "Units" : `Risk (${state.session.currency})`} error={errors.size}><Input inputMode="decimal" value={f.size} onChange={set("size")} /></Field>
        <Field label="Stop-loss" error={errors.stop}><Input inputMode="decimal" value={f.stop} onChange={set("stop")} /></Field>
        <Field label="Take-profit" error={errors.target}><Input inputMode="decimal" value={f.target} onChange={set("target")} /></Field>
      </div>
      <Field label="Note"><Input value={f.note} onChange={set("note")} maxLength={5000} /></Field>
      <div className="flex gap-2">
        <Button type="button" className="flex-1 bg-gain text-bg" disabled={place.isPending} onClick={() => submit("buy")}>Buy</Button>
        <Button type="button" className="flex-1 bg-loss text-bg" disabled={place.isPending} onClick={() => submit("sell")}>Sell</Button>
      </div>
      {place.isError && <p role="alert" className="text-xs text-loss">{errorMessage(place.error)}</p>}
      <p className="text-xs text-muted">Orders are placed at the cursor and fill from the next bar. A risk amount is turned into units by the server, rounded down to 1,000.</p>
    </form>
  );
}

function FinishPanel({ id, hasPosition, onDone }: { id: string; hasPosition: boolean; onDone: (r: s.BacktestState) => void }) {
  const fin = useMutation({
    mutationFn: () => api(`/backtests/${id}/finish`, { method: "POST", body: { flatten: true }, schema: s.backtestState }),
    onSuccess: onDone,
  });
  return (
    <Panel title="Finish">
      <p className="mb-2 text-xs text-muted">{hasPosition ? "The open position will be closed at the last revealed close, with slippage. " : ""}Pending orders are cancelled.</p>
      <Button variant="ghost" disabled={fin.isPending} onClick={() => { if (confirm("Finish this backtest?")) fin.mutate(); }}>Finish session</Button>
      {fin.isError && <p role="alert" className="mt-1 text-xs text-loss">{errorMessage(fin.error)}</p>}
    </Panel>
  );
}

function OrdersTable({ state, onDone, canCancel }: { state: s.BacktestState; onDone: (r: s.BacktestState) => void; canCancel: boolean }) {
  const cancel = useMutation({
    mutationFn: (oid: string) => api(`/backtests/${state.session.id}/orders/${oid}/cancel`, { method: "POST", schema: s.backtestState }),
    onSuccess: onDone,
  });
  if (state.orders.length === 0) return <p className="text-sm text-muted">No orders yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm" data-testid="backtest-orders">
        <thead className="text-left text-xs text-muted uppercase"><tr className="border-b border-line">
          <th className="py-2 pr-3">#</th><th className="pr-3">Placed</th><th className="pr-3">Order</th><th className="pr-3 text-right">Units</th>
          <th className="pr-3 text-right">Price</th><th className="pr-3 text-right">Stop / target</th><th className="pr-3">Status</th><th />
        </tr></thead>
        <tbody className="num">
          {state.orders.map((o) => (
            <tr key={o.id} className="border-b border-line/60">
              <td className="py-1.5 pr-3">{o.seq}</td>
              <td className="pr-3 whitespace-nowrap">{fmtDateTime(o.placed_at)}</td>
              <td className="pr-3">{o.kind === "entry" ? `${o.side} ${o.type}` : o.kind === "stop_loss" ? `stop-loss (${o.side})` : `take-profit (${o.side})`}</td>
              <td className="pr-3 text-right">{fmtNum(o.quantity, 0)}</td>
              <td className="pr-3 text-right">{o.price ? trimDecimal(o.price) : "—"}</td>
              <td className="pr-3 text-right">{o.kind === "entry" ? `${o.stop_loss ? trimDecimal(o.stop_loss) : "—"} / ${o.take_profit ? trimDecimal(o.take_profit) : "—"}` : ""}</td>
              <td className="pr-3"><Badge tone={o.status === "filled" ? "gain" : o.status === "pending" ? "accent" : "muted"}>{o.status}</Badge>{o.reason && <span className="ml-1 text-xs text-muted">{o.reason}</span>}</td>
              <td>{canCancel && o.status === "pending" && <button className="text-xs text-muted hover:text-loss" onClick={() => cancel.mutate(o.id)} aria-label={`Cancel order ${o.seq}`}>Cancel</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {cancel.isError && <p role="alert" className="text-xs text-loss">{errorMessage(cancel.error)}</p>}
    </div>
  );
}

function FillsTable({ state }: { state: s.BacktestState }) {
  if (state.fills.length === 0) return <p className="text-sm text-muted">No fills yet.</p>;
  const c = state.session.currency;
  return (
    <ul className="space-y-1 text-sm" data-testid="backtest-fills">
      {state.fills.map((f) => (
        <li key={f.id} className="flex flex-wrap gap-x-2">
          <span className="text-xs text-muted">{fmtDateTime(f.ts)}</span>
          <span>{f.side} {fmtNum(f.quantity, 0)} @ {trimDecimal(f.price)}</span>
          <span className="text-xs text-muted">{f.kind.replace("_", "-")} · fee {fmtMoney(f.commission, c)}</span>
          {f.ambiguous && <Badge tone="warn">ambiguous</Badge>}
          {f.reason && <span className="w-full text-xs text-muted">{f.reason}</span>}
        </li>
      ))}
    </ul>
  );
}

function TradesTable({ trades, currency }: { trades: s.SimTrade[]; currency: string }) {
  if (trades.length === 0) return <p className="text-sm text-muted">No simulated trades yet.</p>;
  return (
    <table className="w-full text-sm" data-testid="backtest-trades">
      <thead className="text-left text-xs text-muted uppercase"><tr className="border-b border-line">
        <th className="py-2 pr-3">#</th><th className="pr-3">Direction</th><th className="pr-3 text-right">Entry</th><th className="pr-3 text-right">Exit</th>
        <th className="pr-3 text-right">Net</th><th className="pr-3 text-right">R</th>
      </tr></thead>
      <tbody className="num">
        {trades.map((t) => (
          <tr key={t.id} className="border-b border-line/60">
            <td className="py-1.5 pr-3">{t.number}</td>
            <td className="pr-3">{t.direction}{t.status === "open" && <span className="ml-1"><Badge tone="warn">open</Badge></span>}{t.ambiguous && <span className="ml-1"><Badge tone="warn">?</Badge></span>}</td>
            <td className="pr-3 text-right">{trimDecimal(t.entry_avg_price)}</td>
            <td className="pr-3 text-right">{t.exit_avg_price ? trimDecimal(t.exit_avg_price) : "—"}</td>
            <td className={`pr-3 text-right ${pnlClass(t.net_pnl)}`}>{fmtMoney(t.net_pnl, currency, { sign: true })}</td>
            <td className="pr-3 text-right">{fmtR(t.r_multiple)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ResultsPanel({ id, results }: { id: string; results: ReturnType<typeof useBacktestResults> }) {
  const verify = useQuery({ queryKey: ["backtest-verify", id], queryFn: () => api(`/backtests/${id}/verify`, { schema: s.backtestVerify }), enabled: false });
  if (results.isLoading) return <Loading />;
  if (results.isError) return <ErrorState error={results.error} onRetry={() => results.refetch()} />;
  const r = results.data!;
  const sm = r.summary as Record<string, string | number | null>;
  const c = r.currency;
  return (
    <Panel title="Results">
      <div className="space-y-4" data-testid="backtest-results">
        {r.warnings.map((w) => <p key={w} className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm">{w}</p>)}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {[
            ["Net P&L", fmtMoney(r.realized_net_pnl, c, { sign: true }), pnlClass(r.realized_net_pnl)],
            ["Return", fmtPct(r.return_pct, 2), pnlClass(r.return_pct)],
            ["Closed trades", String(sm.closed_trades ?? 0), ""],
            ["Win rate", fmtPct(sm.win_rate as string | null), ""],
            ["Profit factor", fmtRatio(sm.profit_factor as string | null), ""],
            ["Max drawdown", fmtMoney(sm.max_drawdown as string | null, c), ""],
          ].map(([k, v, cls]) => (
            <div key={k} className="rounded-xl border border-line bg-panel-2 p-3"><div className="text-xs text-muted">{k}</div><div className={`num text-lg font-semibold ${cls}`}>{v}</div></div>
          ))}
        </div>
        {r.equity_curve.length > 0 && <EquityCurve data={r.equity_curve} currency={c} onSelect={() => undefined} />}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Button variant="ghost" onClick={() => void verify.refetch()} disabled={verify.isFetching}>Re-run and verify</Button>
          {verify.data && (verify.data.reproducible
            ? <span className="text-gain" data-testid="verify-result">✓ Reproducible: {verify.data.rerun_fills} fills match ({verify.data.simulator})</span>
            : <span className="text-loss" data-testid="verify-result">✕ Re-run differs from the stored fills</span>)}
          {verify.isError && <span className="text-loss">{errorMessage(verify.error)}</span>}
        </div>
        <p className="text-xs text-muted">{r.disclaimer}</p>
      </div>
    </Panel>
  );
}

function Notes({ session }: { session: s.BacktestSession }) {
  const qc = useQueryClient();
  const [text, setText] = useState(session.notes ?? "");
  const save = useMutation({
    mutationFn: () => api(`/backtests/${session.id}`, { method: "PATCH", body: { notes: text }, schema: s.backtestState }),
    onSuccess: (r) => qc.setQueryData(["backtest", session.id], r),
  });
  return (
    <div className="space-y-2">
      <textarea aria-label="Session notes" className="h-24 w-full rounded-lg border border-line bg-panel-2 p-2 text-sm" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={() => save.mutate()} disabled={save.isPending}>Save notes</Button>
        {save.isSuccess && <span className="text-xs text-gain">Saved</span>}
        {save.isError && <span role="alert" className="text-xs text-loss">{errorMessage(save.error)}</span>}
      </div>
    </div>
  );
}

function Screenshots({ id }: { id: string }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["backtest-attachments", id], queryFn: () => api(`/backtests/${id}/attachments`, { schema: z.array(s.attachment) }) });
  const up = useMutation({
    mutationFn: (file: File) => { const form = new FormData(); form.append("file", file); return api(`/backtests/${id}/attachments`, { method: "POST", form }); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backtest-attachments", id] }),
  });
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2">
        {list.data?.map((a) => (
          <a key={a.id} href={`/api/v1/attachments/${a.id}/content`} target="_blank" rel="noreferrer">
            <img src={`/api/v1/attachments/${a.id}/content`} alt={a.filename} className="h-24 w-full rounded object-cover" />
          </a>
        ))}
      </div>
      <label className="inline-block cursor-pointer rounded-lg border border-line bg-panel-2 px-3 py-2 text-sm hover:border-accent">
        {up.isPending ? "Uploading…" : "Add screenshot"}
        <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = ""; }} />
      </label>
      {up.isError && <p role="alert" className="text-xs text-loss">{errorMessage(up.error)}</p>}
    </div>
  );
}
