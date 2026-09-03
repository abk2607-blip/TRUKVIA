import React from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import Dashboard from "@/pages/Dashboard";
import Trips from "@/pages/Trips";
import TripForm from "@/pages/TripForm";
import TripView from "@/pages/TripView";
import Customers from "@/pages/Customers";
import CustomerHistory from "@/pages/CustomerHistory";
import Suppliers from "@/pages/Suppliers";
import Drivers from "@/pages/Drivers";
import DriverShortagePolicies from "@/pages/DriverShortagePolicies";
import DriverTripHistory from "@/pages/DriverTripHistory";
import DriverLedger from "@/pages/DriverLedger";
import HaltingVerify from "@/pages/HaltingVerify";
import Products from "@/pages/Products";
import Vehicles from "@/pages/Vehicles";
import VehicleCostReport from "@/pages/VehicleCostReport";
import ExpenseRegister from "@/pages/ExpenseRegister";
import PartyLedger from "@/pages/PartyLedger";
import Vendors from "@/pages/Vendors";
import Mechanics from "@/pages/Mechanics";
import RepairWorkspace from "@/pages/RepairWorkspace";
import Fuel from "@/pages/Fuel";
import Files from "@/pages/Files";
import AuditLog from "@/pages/AuditLog";
import Team from "@/pages/Team";
import Reports from "@/pages/Reports";
import OverdueInvoices from "@/pages/OverdueInvoices";
import Parties from "@/pages/Parties";
import Invoices from "@/pages/Invoices";
import InvoiceCreate from "@/pages/InvoiceCreate";
import InvoiceView from "@/pages/InvoiceView";
import Notes from "@/pages/Notes";
import DeployHistoryPage from "@/pages/DeployHistoryPage";
import Settings from "@/pages/Settings";
import TripImport from "@/pages/TripImport";
import TripTemplates from "@/pages/TripTemplates";
import Layout from "@/components/Layout";

function Protected({ children }) {
  const { user, loading } = useAuth();
  // If cached user exists, render immediately while /auth/me verifies in background.
  if (loading && !user) {
    return (
      <div className="flex items-center justify-center h-screen text-zinc-500" data-testid="loading-screen">
        Loading...
      </div>
    );
  }
  if (!user) return <Navigate to="/" replace />;
  return <Layout>{children}</Layout>;
}

function AppRouter() {
  const location = useLocation();
  // Detect OAuth callback synchronously during render (before ProtectedRoute)
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
      <Route path="/admin/deploy-history" element={<Protected><DeployHistoryPage /></Protected>} />
      <Route path="/trips" element={<Protected><Trips /></Protected>} />
      <Route path="/trips/new" element={<Protected><TripForm /></Protected>} />
      <Route path="/trips/import" element={<Protected><TripImport /></Protected>} />
      <Route path="/trips/templates" element={<Protected><TripTemplates /></Protected>} />
      <Route path="/trips/:id/edit" element={<Protected><TripForm /></Protected>} />
      <Route path="/trips/:id/view" element={<Protected><TripView /></Protected>} />
      <Route path="/customers" element={<Protected><Customers /></Protected>} />
      <Route path="/customers/history" element={<Protected><CustomerHistory /></Protected>} />
      <Route path="/customers/history/:id" element={<Protected><CustomerHistory /></Protected>} />
      <Route path="/suppliers/*" element={<Protected><Suppliers /></Protected>} />
      <Route path="/parties" element={<Protected><Parties /></Protected>} />
      <Route path="/drivers" element={<Protected><Drivers /></Protected>} />
      <Route path="/drivers/shortage-policies" element={<Protected><DriverShortagePolicies /></Protected>} />
      <Route path="/drivers/:id/history" element={<Protected><DriverTripHistory /></Protected>} />
      <Route path="/drivers/:id/ledger" element={<Protected><DriverLedger /></Protected>} />
      <Route path="/reports/halting-verify" element={<Protected><HaltingVerify /></Protected>} />
      <Route path="/vehicles" element={<Protected><Vehicles /></Protected>} />
      <Route path="/expenses" element={<Protected><ExpenseRegister /></Protected>} />
      <Route path="/vehicles/:vid/cost" element={<Protected><VehicleCostReport /></Protected>} />
      <Route path="/vehicles/:vid/repairs/new" element={<Protected><RepairWorkspace /></Protected>} />
      <Route path="/repairs/:rid" element={<Protected><RepairWorkspace /></Protected>} />
      <Route path="/vendors" element={<Protected><Vendors /></Protected>} />
      <Route path="/mechanics" element={<Protected><Mechanics /></Protected>} />
      <Route path="/vendor-ledger/:id" element={<Protected><PartyLedger partyType="vendor" /></Protected>} />
      <Route path="/mechanic-ledger/:id" element={<Protected><PartyLedger partyType="mechanic" /></Protected>} />
      <Route path="/products" element={<Protected><Products /></Protected>} />
      <Route path="/fuel" element={<Protected><Fuel /></Protected>} />
      <Route path="/files" element={<Protected><Files /></Protected>} />
      <Route path="/audit" element={<Protected><AuditLog /></Protected>} />
      <Route path="/team" element={<Protected><Team /></Protected>} />
      <Route path="/reports/*" element={<Protected><Reports /></Protected>} />
      <Route path="/invoices/overdue" element={<Protected><OverdueInvoices /></Protected>} />
      <Route path="/invoices" element={<Protected><Invoices /></Protected>} />
      <Route path="/invoices/new" element={<Protected><InvoiceCreate /></Protected>} />
      <Route path="/invoices/:id" element={<Protected><InvoiceView /></Protected>} />
      <Route path="/notes" element={<Protected><Notes /></Protected>} />
      <Route path="/settings" element={<Protected><Settings /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <AuthProvider>
      <AppRouter />
    </AuthProvider>
  );
}

export default App;
