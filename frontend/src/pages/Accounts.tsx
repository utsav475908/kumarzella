import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "../api/client";
import { qk, useAccounts } from "../api/hooks";
import { Badge, Button, Empty, ErrorState, Field, Input, Loading, Panel, Select, errorMessage } from "../components/ui";
import { fmtMoney } from "../lib/format";

const decimalOpt = z.string().trim().regex(/^(\d+(\.\d+)?)?$/, "Enter a positive number");
export const accountSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(120),
  broker: z.string().trim().max(120),
  account_type: z.enum(["live", "paper", "demo"]),
  base_currency: z.string().regex(/^[A-Z]{3}$/, "3-letter ISO code"),
  accounting_policy: z.enum(["average_cost", "fifo"]),
  starting_balance: decimalOpt,
  max_risk_per_trade: decimalOpt,
  daily_loss_limit: decimalOpt,
});

export function AccountsPage() {
  const accounts = useAccounts();
  const qc = useQueryClient();
  const [v, setV] = useState({ name: "", broker: "", account_type: "live", base_currency: "USD", accounting_policy: "average_cost", starting_balance: "", max_risk_per_trade: "", daily_loss_limit: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/accounts", { method: "POST", body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.accounts }); setV({ ...v, name: "", broker: "" }); },
  });
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const r = accountSchema.safeParse(v);
    if (!r.success) { setErrors(Object.fromEntries(r.error.issues.map((i) => [String(i.path[0]), i.message]))); return; }
    setErrors({});
    const d = r.data;
    create.mutate({ ...d, broker: d.broker || null, starting_balance: d.starting_balance || null, max_risk_per_trade: d.max_risk_per_trade || null, daily_loss_limit: d.daily_loss_limit || null });
  };
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Trading accounts</h1>
      <Panel title="Your accounts">
        {accounts.isLoading && <Loading />}
        {accounts.isError && <ErrorState error={accounts.error} onRetry={() => accounts.refetch()} />}
        {accounts.data?.length === 0 && <Empty title="No accounts yet">Create one below, then import a CSV into it.</Empty>}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {accounts.data?.map((a) => (
            <div key={a.id} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex items-center justify-between font-medium">{a.name}<Badge tone={a.is_demo ? "warn" : "muted"}>{a.account_type}</Badge></div>
              <div className="mt-1 text-muted">{a.broker ?? "No broker set"} · {a.base_currency} · {a.accounting_policy.replace("_", " ")}</div>
              <div className="num mt-1 text-muted">Start {fmtMoney(a.starting_balance, a.base_currency)} · max risk {fmtMoney(a.max_risk_per_trade, a.base_currency)} · daily limit {fmtMoney(a.daily_loss_limit, a.base_currency)}</div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Add account">
        <form onSubmit={submit} className="grid max-w-3xl gap-3 md:grid-cols-3" noValidate>
          <Field label="Name" error={errors.name}><Input value={v.name} onChange={set("name")} /></Field>
          <Field label="Broker" error={errors.broker}><Input value={v.broker} onChange={set("broker")} /></Field>
          <Field label="Type"><Select className="w-full" value={v.account_type} onChange={set("account_type")}><option value="live">Live</option><option value="paper">Paper</option><option value="demo">Demo (synthetic data)</option></Select></Field>
          <Field label="Base currency" error={errors.base_currency}><Input value={v.base_currency} onChange={(e) => setV({ ...v, base_currency: e.target.value.toUpperCase() })} /></Field>
          <Field label="Position accounting" hint="Only affects realized P&L on partially closed open trades">
            <Select className="w-full" value={v.accounting_policy} onChange={set("accounting_policy")}><option value="average_cost">Average cost</option><option value="fifo">FIFO</option></Select>
          </Field>
          <Field label="Starting balance" error={errors.starting_balance}><Input inputMode="decimal" value={v.starting_balance} onChange={set("starting_balance")} /></Field>
          <Field label="Max risk per trade" error={errors.max_risk_per_trade}><Input inputMode="decimal" value={v.max_risk_per_trade} onChange={set("max_risk_per_trade")} /></Field>
          <Field label="Daily loss limit" error={errors.daily_loss_limit}><Input inputMode="decimal" value={v.daily_loss_limit} onChange={set("daily_loss_limit")} /></Field>
          <div className="flex items-end"><Button type="submit" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create account"}</Button></div>
          {create.isError && <p role="alert" className="text-sm text-loss md:col-span-3">{errorMessage(create.error)}</p>}
        </form>
      </Panel>
    </div>
  );
}
