import { useEffect, useState } from "react";
import { useAccounts, usePlaybooks, useTags } from "../api/hooks";
import { useFilters, type Filters } from "../lib/filters";
import { Button, Input, Select } from "./ui";

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] ?? "" : v ?? "");

export function FilterBar() {
  const [f, setF] = useFilters();
  const accounts = useAccounts();
  const playbooks = usePlaybooks();
  const tags = useTags();
  const [symbols, setSymbols] = useState(Array.isArray(f.symbol) ? f.symbol.join(", ") : f.symbol ?? "");
  const symbolKey = JSON.stringify(f.symbol ?? []);
  useEffect(() => {
    setSymbols(Array.isArray(f.symbol) ? f.symbol.join(", ") : f.symbol ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolKey]);

  const update = (k: keyof Filters, v: string) => {
    const next: Filters = { ...f };
    if (v) next[k] = v;
    else delete next[k];
    setF(next);
  };
  const applySymbols = () => {
    const list = symbols.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
    const next: Filters = { ...f };
    if (list.length) next.symbol = list;
    else delete next.symbol;
    setF(next);
  };
  const active = Object.keys(f).length;

  return (
    <div className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-panel p-3" aria-label="Filters">
      <Select aria-label="Account" value={first(f.account_id)} onChange={(e) => update("account_id", e.target.value)}>
        <option value="">All accounts</option>
        {accounts.data?.map((a) => (
          <option key={a.id} value={a.id}>{a.name}{a.is_demo ? " (demo)" : ""}</option>
        ))}
      </Select>
      <Input aria-label="From date" type="date" className="!w-auto" value={first(f.date_from)} onChange={(e) => update("date_from", e.target.value)} />
      <Input aria-label="To date" type="date" className="!w-auto" value={first(f.date_to)} onChange={(e) => update("date_to", e.target.value)} />
      <form onSubmit={(e) => { e.preventDefault(); applySymbols(); }}>
        <Input aria-label="Symbols" placeholder="Symbols, e.g. AAPL, ES" className="!w-44" value={symbols} onChange={(e) => setSymbols(e.target.value)} onBlur={applySymbols} />
      </form>
      <Select aria-label="Asset class" value={first(f.asset_class)} onChange={(e) => update("asset_class", e.target.value)}>
        <option value="">All assets</option>
        {["stock", "etf", "option", "future", "forex", "crypto"].map((a) => (
          <option key={a} value={a}>{a}</option>
        ))}
      </Select>
      <Select aria-label="Strategy" value={first(f.playbook_id)} onChange={(e) => update("playbook_id", e.target.value)}>
        <option value="">All strategies</option>
        <option value="none">No playbook</option>
        {playbooks.data?.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </Select>
      <Select aria-label="Tag" value={first(f.tag_id)} onChange={(e) => update("tag_id", e.target.value)}>
        <option value="">All tags</option>
        {tags.data?.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </Select>
      <Select aria-label="Direction" value={first(f.direction)} onChange={(e) => update("direction", e.target.value)}>
        <option value="">Long & short</option>
        <option value="long">Long</option>
        <option value="short">Short</option>
      </Select>
      <Select aria-label="Session" value={first(f.session)} onChange={(e) => update("session", e.target.value)}>
        <option value="">All sessions</option>
        <option value="regular">Regular hours</option>
        <option value="extended">Extended hours</option>
      </Select>
      {active > 0 && (
        <Button variant="ghost" onClick={() => setF({})}>
          Clear ({active})
        </Button>
      )}
    </div>
  );
}
