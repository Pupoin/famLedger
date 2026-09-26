import { lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { DateFormatProvider } from "./DateFormatContext";
import ErrorBoundary from "./ErrorBoundary";
import Navbar from "./components/Navbar";
import Landing from "./pages/Landing";
import AddExpense from "./pages/AddExpense";
import AddNew from "./pages/AddNew";
import History from "./pages/History";
import Login from "./pages/Login";
import CreateAccount from "./pages/CreateAccount";
import ForgotPassword from "./pages/ForgotPassword";
import Settings from "./pages/Settings";
import RulesPage from "./pages/RulesPage";
import DebtsPage from "./pages/DebtsPage";
import EmailsPage from "./pages/EmailsPage";
import ModeSwitchBanner from "./components/ModeSwitchBanner";

// A lazily loaded route whose chunk fails to load almost always means this tab
// is running an index.html from an older build and asking for chunk names the
// server no longer has (see the Cache-Control note in backend/main.py). The
// index.html is no longer cacheable without revalidation, so a plain reload
// fetches the current one and fixes it — but a tab opened before that change
// shipped still has the stale copy, and the error it shows ("Something went
// wrong") tells the user nothing about what to do. Reload once instead.
const RELOAD_FLAG = "famledger:chunk-reload";

function lazyWithReload(importer) {
  return lazy(() =>
    importer()
      .then((mod) => {
        // Import succeeded, so the tab is current: clear the guard so a future
        // deploy gets its own one reload rather than inheriting a spent one.
        try {
          sessionStorage.removeItem(RELOAD_FLAG);
        } catch {
          /* storage unavailable (private mode) — nothing to clear */
        }
        return mod;
      })
      .catch((err) => {
        // Default to "already reloaded" when sessionStorage is unreadable: the
        // guard exists to stop a reload loop when the chunk is genuinely gone
        // rather than merely stale, and failing closed keeps that guarantee.
        let alreadyReloaded = true;
        try {
          alreadyReloaded = sessionStorage.getItem(RELOAD_FLAG) === "1";
          if (!alreadyReloaded) sessionStorage.setItem(RELOAD_FLAG, "1");
        } catch {
          /* storage unavailable — surface the error to the ErrorBoundary */
        }
        if (alreadyReloaded) throw err;
        window.location.reload();
        // Never settles; the reload replaces the page before React sees it.
        return new Promise(() => {});
      }),
  );
}

const Analytics = lazyWithReload(() => import("./pages/Analytics"));
const Calendar = lazyWithReload(() => import("./pages/Calendar"));
const Insights = lazyWithReload(() => import("./pages/Insights"));

export default function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (!user?.username) {
    return (
      <Routes>
        <Route path="/create-account" element={<CreateAccount />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }

  return (
    <DateFormatProvider>
    <div className="min-h-screen bg-background font-body text-on-surface">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-24 pb-32 md:pb-8">
        <ModeSwitchBanner />
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/add" element={<AddNew />} />
            <Route path="/edit/:id" element={<AddExpense />} />
            <Route path="/add-income" element={<Navigate to="/add?tab=income" replace />} />
            <Route path="/analytics" element={
              <Suspense fallback={
                <div className="flex items-center justify-center h-64">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              }>
                <Analytics />
              </Suspense>
            } />
            <Route path="/calendar" element={
              <Suspense fallback={
                <div className="flex items-center justify-center h-64">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              }>
                <Calendar />
              </Suspense>
            } />
            <Route path="/insights" element={
              <Suspense fallback={
                <div className="flex items-center justify-center h-64">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              }>
                <Insights />
              </Suspense>
            } />
            <Route path="/history" element={<History />} />
            <Route path="/rules" element={<RulesPage />} />
            <Route path="/debts" element={<DebtsPage />} />
            <Route path="/emails" element={<EmailsPage />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
    </DateFormatProvider>
  );
}
