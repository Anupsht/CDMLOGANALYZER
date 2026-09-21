import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import { Spinner } from "./components/ui";

// Phase 7: heavy technician pages are code-split (lazy loading).
const Transactions = lazy(() => import("./pages/Transactions"));
const TransactionDetail = lazy(() => import("./pages/TransactionDetail"));
const MachineHealth = lazy(() => import("./pages/MachineHealth"));
const LogViewer = lazy(() => import("./pages/LogViewer"));
const Logs = lazy(() => import("./pages/Logs"));
const Models = lazy(() => import("./pages/Models"));
const Machines = lazy(() => import("./pages/Machines"));

export default function App() {
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
