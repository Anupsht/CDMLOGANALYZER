import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import { Spinner } from "./components/ui";
import { useAuth } from "./auth";
import Login from "./pages/Login";

// Phase 7: heavy technician pages are code-split (lazy loading).
const Transactions = lazy(() => import("./pages/Transactions"));
const TransactionDetail = lazy(() => import("./pages/TransactionDetail"));
const MachineHealth = lazy(() => import("./pages/MachineHealth"));
const Analytics = lazy(() => import("./pages/Analytics"));
const LogViewer = lazy(() => import("./pages/LogViewer"));
const Logs = lazy(() => import("./pages/Logs"));
const Models = lazy(() => import("./pages/Models"));
const Machines = lazy(() => import("./pages/Machines"));
const Cases = lazy(() => import("./pages/Cases"));
const Users = lazy(() => import("./pages/Users"));

export default function App() {
  const { token } = useAuth();

  // Phase 10: every screen sits behind authentication.
  if (!token) return <Login />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route
          path="/transactions"
          element={
            <Suspense fallback={<Spinner />}>
              <Transactions />
            </Suspense>
          }
        />
        <Route
          path="/transactions/:txnId"
          element={
            <Suspense fallback={<Spinner />}>
              <TransactionDetail />
            </Suspense>
          }
        />
        <Route
          path="/health"
          element={
            <Suspense fallback={<Spinner />}>
              <MachineHealth />
            </Suspense>
          }
        />
        <Route
          path="/cases"
          element={
            <Suspense fallback={<Spinner />}>
              <Cases />
            </Suspense>
          }
        />
        <Route
          path="/users"
          element={
            <Suspense fallback={<Spinner />}>
              <Users />
            </Suspense>
          }
        />
        <Route
          path="/analytics"
          element={
            <Suspense fallback={<Spinner />}>
              <Analytics />
            </Suspense>
          }
        />
        <Route
          path="/logs"
          element={
            <Suspense fallback={<Spinner />}>
              <Logs />
            </Suspense>
          }
        />
        <Route
          path="/logs/:fileId"
          element={
            <Suspense fallback={<Spinner />}>
              <LogViewer />
            </Suspense>
          }
        />
        <Route
          path="/models"
          element={
            <Suspense fallback={<Spinner />}>
              <Models />
            </Suspense>
          }
        />
        <Route
          path="/machines"
          element={
            <Suspense fallback={<Spinner />}>
              <Machines />
            </Suspense>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
