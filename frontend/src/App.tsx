import { Navigate, Route, Routes } from "react-router";
import { useMe } from "./api/hooks";
import { Layout, useTheme } from "./components/Layout";
import { ErrorState, Loading } from "./components/ui";
import { AccountsPage } from "./pages/Accounts";
import { LoginPage, RegisterPage } from "./pages/Auth";
import { BacktestListPage, BacktestPage } from "./pages/Backtest";
import { CalendarPage } from "./pages/CalendarPage";
import { CoachPage } from "./pages/Coach";
import { DashboardPage } from "./pages/Dashboard";
import { ImportWizard } from "./pages/ImportWizard";
import { PlaybookPage, PlaybooksPage } from "./pages/Playbooks";
import { ReportsPage } from "./pages/Reports";
import { ReplayListPage, ReplayPlayerPage } from "./pages/Replay";
import { ImportsPage, SettingsPage } from "./pages/Settings";
import { TradeDetailPage } from "./pages/TradeDetail";
import { TradesPage } from "./pages/Trades";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const me = useMe();
  if (me.isLoading) return <Loading label="Checking your session…" />;
  if (me.isError) return <div className="p-6"><ErrorState error={me.error} onRetry={() => me.refetch()} /></div>;
  if (!me.data) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  useTheme();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<DashboardPage />} />
        <Route path="trades" element={<TradesPage />} />
        <Route path="trades/:id" element={<TradeDetailPage />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="import" element={<ImportWizard />} />
        <Route path="imports" element={<ImportsPage />} />
        <Route path="replay" element={<ReplayListPage />} />
        <Route path="replay/:id" element={<ReplayPlayerPage />} />
        <Route path="coach" element={<CoachPage />} />
        <Route path="backtest" element={<BacktestListPage />} />
        <Route path="backtest/:id" element={<BacktestPage />} />
        <Route path="playbooks" element={<PlaybooksPage />} />
        <Route path="playbooks/:id" element={<PlaybookPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
