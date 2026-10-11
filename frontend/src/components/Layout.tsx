import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import clsx from "clsx";
import { useEffect, useState } from "react";
import { useAccounts, useLogout, useMe } from "../api/hooks";
import { filtersToSearch, readFilters } from "../lib/filters";

const NAV = [
  { to: "/", label: "Dashboard", keepFilters: true },
  { to: "/trades", label: "Journal", keepFilters: true },
  { to: "/calendar", label: "Calendar", keepFilters: true },
  { to: "/reports", label: "Reports", keepFilters: true },
  { to: "/coach", label: "AI coach" },
  { to: "/replay", label: "Replay" },
  { to: "/backtest", label: "Backtest" },
  { to: "/import", label: "Import" },
  { to: "/imports", label: "Import history" },
  { to: "/playbooks", label: "Playbooks" },
  { to: "/accounts", label: "Accounts" },
  { to: "/settings", label: "Settings" },
];

export function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => localStorage.getItem("el_theme") ?? "dark");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("el_theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export function Layout() {
  const me = useMe();
  const accounts = useAccounts();
  const logout = useLogout();
  const nav = useNavigate();
  const loc = useLocation();
  const [theme, toggle] = useTheme();
  const filterSearch = filtersToSearch(readFilters(new URLSearchParams(loc.search)));
  const demo = accounts.data?.some((a) => a.is_demo);

  return (
    <div className="flex min-h-full">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-panel p-4 md:flex">
        <div className="mb-6 flex items-center gap-2 text-lg font-semibold">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          EdgeLedger
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.keepFilters ? `${n.to}${filterSearch}` : n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                clsx("rounded-lg px-3 py-2 text-sm", isActive ? "bg-accent/15 text-accent" : "text-muted hover:bg-panel-2 hover:text-fg")
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-2 border-t border-line pt-4 text-sm">
          <div className="truncate text-muted" title={me.data?.email}>{me.data?.display_name}</div>
          <div className="flex gap-2">
            <button className="text-muted hover:text-fg" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? "Light mode" : "Dark mode"}
            </button>
            <span className="text-line">|</span>
            <button className="text-muted hover:text-fg" onClick={() => logout.mutate(undefined, { onSuccess: () => nav("/login") })}>
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-line bg-panel px-4 py-3 md:hidden">
          <span className="font-semibold">EdgeLedger</span>
          <select className="rounded border border-line bg-panel-2 px-2 py-1 text-sm" value={loc.pathname} onChange={(e) => nav(e.target.value)} aria-label="Navigate">
            {NAV.map((n) => (
              <option key={n.to} value={n.to}>{n.label}</option>
            ))}
          </select>
        </header>
        {demo && (
          <div className="border-b border-warn/40 bg-warn/10 px-4 py-2 text-xs text-warn">
            Demo mode: an account marked "demo" contains synthetic sample data, not real broker executions.
          </div>
        )}
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
