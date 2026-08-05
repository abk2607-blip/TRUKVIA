import React from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import Dashboard from "@/pages/Dashboard";
import Trips from "@/pages/Trips";
import TripForm from "@/pages/TripForm";
import Customers from "@/pages/Customers";
import Invoices from "@/pages/Invoices";
import InvoiceCreate from "@/pages/InvoiceCreate";
import InvoiceView from "@/pages/InvoiceView";
import Settings from "@/pages/Settings";
import Layout from "@/components/Layout";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
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
      <Route path="/trips" element={<Protected><Trips /></Protected>} />
      <Route path="/trips/new" element={<Protected><TripForm /></Protected>} />
      <Route path="/trips/:id/edit" element={<Protected><TripForm /></Protected>} />
      <Route path="/customers" element={<Protected><Customers /></Protected>} />
      <Route path="/invoices" element={<Protected><Invoices /></Protected>} />
      <Route path="/invoices/new" element={<Protected><InvoiceCreate /></Protected>} />
      <Route path="/invoices/:id" element={<Protected><InvoiceView /></Protected>} />
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
