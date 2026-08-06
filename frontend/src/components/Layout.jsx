import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  LayoutDashboard, Truck, Users, FileText, Settings as SettingsIcon, LogOut, UserCog, Package, BarChart3, Car, Fuel as FuelIcon, FolderArchive, History, ShieldCheck, MapPin, AlertCircle,
} from "lucide-react";

const nav = [
  { to: "/dashboard", te: "డ్యాష్‌బోర్డ్", en: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
  { to: "/trips", te: "ట్రిప్స్", en: "Trips", icon: Truck, testid: "nav-trips" },
  { to: "/customers", te: "కస్టమర్లు", en: "Customers", icon: Users, testid: "nav-customers" },
  { to: "/parties", te: "కన్‌సైనర్/కన్‌సైనీ", en: "Consignor/Consignee", icon: MapPin, testid: "nav-parties" },
  { to: "/vehicles", te: "వాహనాలు", en: "Vehicles", icon: Car, testid: "nav-vehicles" },
  { to: "/drivers", te: "డ్రైవర్లు", en: "Drivers", icon: UserCog, testid: "nav-drivers" },
  { to: "/products", te: "ప్రొడక్ట్‌లు", en: "Products", icon: Package, testid: "nav-products" },
  { to: "/fuel", te: "డీజిల్", en: "Fuel", icon: FuelIcon, testid: "nav-fuel" },
  { to: "/invoices", te: "ఇన్వాయిస్‌లు", en: "Invoices", icon: FileText, testid: "nav-invoices" },
  { to: "/invoices/overdue", te: "బకాయిలు", en: "Overdue", icon: AlertCircle, testid: "nav-overdue" },
  { to: "/reports", te: "రిపోర్ట్‌లు", en: "Reports", icon: BarChart3, testid: "nav-reports" },
  { to: "/files", te: "ఫైల్‌లు", en: "Files", icon: FolderArchive, testid: "nav-files" },
  { to: "/team", te: "టీమ్", en: "Team", icon: ShieldCheck, testid: "nav-team" },
  { to: "/audit", te: "ఆడిట్", en: "Audit Log", icon: History, testid: "nav-audit" },
  { to: "/settings", te: "సెట్టింగ్‌లు", en: "Settings", icon: SettingsIcon, testid: "nav-settings" },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex bg-zinc-100">
      {/* Sidebar */}
      <aside className="hidden md:flex md:w-64 bg-white border-r border-zinc-200 flex-col" data-testid="sidebar">
        <div className="px-6 py-6 border-b border-zinc-200">
          <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-zinc-500">Bitumen Transport</div>
          <div className="mt-1 font-black text-xl tracking-tight text-zinc-950">అకౌంటింగ్</div>
          <div className="text-xs text-zinc-500">Accounting Suite</div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              data-testid={n.testid}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm border transition-colors ${
                  isActive
                    ? "bg-zinc-950 text-white border-zinc-950"
                    : "border-transparent text-zinc-700 hover:bg-zinc-100 hover:border-zinc-200"
                }`
              }
            >
              <n.icon size={18} strokeWidth={1.75} />
              <span>
                <span className="telugu">{n.te}</span>{" "}
                <span className="text-[11px] opacity-70">({n.en})</span>
              </span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-zinc-200 p-3">
          <div className="flex items-center gap-2 px-2 py-2">
            {user?.picture ? (
              <img src={user.picture} alt="" className="w-8 h-8 rounded-full" />
            ) : (
              <div className="w-8 h-8 rounded-full bg-zinc-200" />
            )}
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold truncate">{user?.name}</div>
              <div className="text-[10px] text-zinc-500 truncate">{user?.email}</div>
            </div>
          </div>
          <button
            data-testid="logout-button"
            onClick={logout}
            className="mt-2 w-full flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-zinc-200 hover:bg-zinc-950 hover:text-white transition-colors rounded-sm"
          >
            <LogOut size={14} /> Logout
          </button>
        </div>
      </aside>

      {/* Content */}
      <main className="flex-1 min-w-0">
        {/* Mobile top bar */}
        <div className="md:hidden bg-white border-b border-zinc-200 px-4 py-3 flex items-center justify-between">
          <div className="font-black tracking-tight">Bitumen A/C</div>
          <div className="flex gap-2 overflow-x-auto">
            {nav.map((n) => (
              <button
                key={n.to}
                onClick={() => navigate(n.to)}
                data-testid={`mobile-${n.testid}`}
                className="px-2 py-1 text-[10px] uppercase border border-zinc-200 rounded-sm"
              >
                {n.en}
              </button>
            ))}
          </div>
        </div>
        <div className="p-4 sm:p-6 lg:p-8 max-w-[1400px] mx-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
