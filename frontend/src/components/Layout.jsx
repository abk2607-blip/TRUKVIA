import React, { useState } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/context/AuthContext";
import { api, getActiveCompanyId, setActiveCompanyId } from "@/api";
import {
  LayoutDashboard, Truck, Users, FileText, Settings as SettingsIcon, LogOut, UserCog, Package, BarChart3, Car, Fuel as FuelIcon, FolderArchive, History, ShieldCheck, MapPin, AlertCircle, Building2, LayoutTemplate, Handshake, Menu, X, MoreHorizontal, FileMinus, Wrench, HardHat, Receipt, BookOpen, BookMarked, CalendarCheck2,
} from "lucide-react";
import AIChatBubble from "@/components/AIChatBubble";
import DeployReadinessBadge from "@/components/DeployReadinessBadge";
import { useCdnEnabled } from "@/hooks/useCdnEnabled";

// Iter150E · 5-section sidebar (Masters / Operations / Financials /
// Reports / System).  All 24 existing route paths and 24 existing
// data-testids are preserved verbatim.  Only 3 new authorised
// Financial Control links are added.
const NAV_SECTIONS = [
  {
    key: "masters",
    label: "Masters",
    testid: "sidebar-section-masters",
    items: [
      { to: "/customers", te: "కస్టమర్లు", en: "Customers", icon: Users, testid: "nav-customers" },
      { to: "/parties", te: "కన్‌సైనర్/కన్‌సైనీ", en: "Consignor/Consignee", icon: MapPin, testid: "nav-parties" },
      { to: "/suppliers", te: "సప్లయర్లు", en: "Suppliers", icon: Handshake, testid: "nav-suppliers" },
      { to: "/vendors", te: "వెండార్లు", en: "Vendors", icon: Wrench, testid: "nav-vendors" },
      { to: "/mechanics", te: "మెకానిక్‌లు", en: "Mechanics", icon: HardHat, testid: "nav-mechanics" },
      { to: "/drivers", te: "డ్రైవర్లు", en: "Drivers", icon: UserCog, testid: "nav-drivers" },
      { to: "/drivers/shortage-policies", te: "షార్టేజ్ పాలసీ", en: "Shortage Policy", icon: UserCog, testid: "nav-shortage-policies" },
      { to: "/vehicles", te: "వాహనాలు", en: "Vehicles", icon: Car, testid: "nav-vehicles" },
      { to: "/products", te: "ప్రొడక్ట్‌లు", en: "Products", icon: Package, testid: "nav-products" },
    ],
  },
  {
    key: "operations",
    label: "Operations",
    testid: "sidebar-section-operations",
    items: [
      { to: "/dashboard", te: "డ్యాష్‌బోర్డ్", en: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
      { to: "/trips", te: "ట్రిప్స్", en: "Trips", icon: Truck, testid: "nav-trips" },
      { to: "/trips/templates", te: "ట్రిప్ టెంప్లేట్‌లు", en: "Trip Templates", icon: LayoutTemplate, testid: "nav-templates" },
      { to: "/customers/history", te: "కస్టమర్ లావాదేవీలు", en: "Customer History", icon: FileText, testid: "nav-customer-history" },
      { to: "/fuel", te: "డీజిల్", en: "Fuel", icon: FuelIcon, testid: "nav-fuel" },
      { to: "/expenses", te: "ఖర్చులు", en: "Expenses", icon: Receipt, testid: "nav-expenses" },
      { to: "/expenses/quick", te: "త్వరిత ఖర్చు", en: "Quick Expense", icon: Receipt, testid: "nav-quick-expense" },
    ],
  },
  {
    key: "financials",
    label: "Financials",
    testid: "sidebar-section-financials",
    items: [
      { to: "/invoices", te: "ఇన్వాయిస్‌లు", en: "Invoices", icon: FileText, testid: "nav-invoices" },
      { to: "/invoices/overdue", te: "బకాయిలు", en: "Overdue", icon: AlertCircle, testid: "nav-overdue" },
      { to: "/notes", te: "క్రెడిట్ / డెబిట్ నోట్‌లు", en: "Credit / Debit Notes", icon: FileMinus, testid: "nav-notes", cdnOnly: true },
      { to: "/fin/day-book", te: "డే బుక్", en: "Day Book", icon: BookOpen, testid: "nav-fin-day-book" },
      { to: "/fin/accounts", te: "అకౌంట్ లెడ్జర్", en: "Account Ledger", icon: BookMarked, testid: "nav-fin-accounts" },
      { to: "/fin/day-closing", te: "డే క్లోజింగ్", en: "Day Closing", icon: CalendarCheck2, testid: "nav-fin-day-closing" },
    ],
  },
  {
    key: "reports",
    label: "Reports",
    testid: "sidebar-section-reports",
    items: [
      { to: "/reports", te: "రిపోర్ట్‌లు", en: "Reports", icon: BarChart3, testid: "nav-reports" },
      { to: "/audit", te: "ఆడిట్", en: "Audit Log", icon: History, testid: "nav-audit" },
    ],
  },
  {
    key: "system",
    label: "System",
    testid: "sidebar-section-system",
    items: [
      { to: "/files", te: "ఫైల్‌లు", en: "Files", icon: FolderArchive, testid: "nav-files" },
      { to: "/team", te: "టీమ్", en: "Team", icon: ShieldCheck, testid: "nav-team" },
      { to: "/settings", te: "సెట్టింగ్‌లు", en: "Settings", icon: SettingsIcon, testid: "nav-settings" },
    ],
  },
];

// Iter75 — Mobile bottom-nav: the 4 daily-driver screens + "More" opens the drawer.
const mobileBottom = [
  { to: "/dashboard", en: "Home", icon: LayoutDashboard, testid: "bnav-dashboard" },
  { to: "/trips", en: "Trips", icon: Truck, testid: "bnav-trips" },
  { to: "/invoices", en: "Invoices", icon: FileText, testid: "bnav-invoices" },
  { to: "/suppliers", en: "Suppliers", icon: Handshake, testid: "bnav-suppliers" },
];

function BrandLockup({ compact = false }) {
  return (
    <div
      className="flex items-center gap-3"
      data-testid={compact ? "sidebar-brand-mark-mobile" : "sidebar-brand-mark"}
    >
      <img
        src="/brand/trukvia-mark-64.png"
        srcSet="/brand/trukvia-mark-64.png 1x, /brand/trukvia-mark-128.png 2x"
        alt="TRUKVIA"
        className={compact ? "h-8 w-auto" : "h-9 w-auto"}
      />
      <div className="min-w-0 leading-tight">
        <div className="text-[11px] font-black uppercase tracking-[0.22em] text-zinc-950">
          TRUKVIA
        </div>
        <div className="mt-0.5 text-[10px] text-zinc-500">
          <span className="telugu">అకౌంటింగ్</span>
          <span className="mx-1 text-zinc-300">·</span>
          Accounting Suite
        </div>
      </div>
    </div>
  );
}

function CompanySwitcher({ companies, activeCid, active, onSwitch }) {
  if (!companies.length) return null;
  return (
    <div className="px-4 py-3 border-b border-zinc-200" data-testid="company-switcher">
      <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 flex items-center gap-1">
        <Building2 size={11} /> Active Company
      </div>
      <select
        data-testid="company-switcher-select"
        value={activeCid}
        onChange={(e) => onSwitch(e.target.value)}
        className="mt-1 w-full border border-zinc-300 px-2 py-2 rounded-sm text-sm font-semibold bg-white focus:border-[hsl(var(--brand))] outline-none min-h-[40px]"
      >
        {companies.map((c) => (
          <option key={c.id} value={c.id}>{c.name || "(unnamed)"}{c.is_default ? " · default" : ""}</option>
        ))}
      </select>
      <div className="mt-1 text-[10px] text-zinc-500">{active?.state || "Set state in Settings"}</div>
    </div>
  );
}

function NavItem({ item, onNavigate }) {
  return (
    <NavLink
      to={item.to}
      data-testid={item.testid}
      onClick={onNavigate}
      className={({ isActive }) =>
        `relative flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm border transition-colors min-h-[40px] ${
          isActive
            ? "bg-zinc-950 text-white border-zinc-950"
            : "border-transparent text-zinc-700 hover:bg-zinc-100 hover:border-zinc-200 active:bg-zinc-200"
        }`
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              aria-hidden="true"
              className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full"
              style={{ backgroundColor: "hsl(var(--brand))" }}
            />
          )}
          <item.icon size={18} strokeWidth={isActive ? 2.25 : 1.75} />
          <span>
            <span className="telugu">{item.te}</span>{" "}
            <span className="text-[11px] opacity-70">({item.en})</span>
          </span>
        </>
      )}
    </NavLink>
  );
}

function NavList({ onNavigate }) {
  const cdnEnabled = useCdnEnabled();
  return (
    <nav className="flex-1 p-3 space-y-4 overflow-y-auto">
      {NAV_SECTIONS.map((section) => {
        const items = section.items.filter((n) => !n.cdnOnly || cdnEnabled);
        if (!items.length) return null;
        return (
          <div key={section.key} data-testid={section.testid}>
            <div className="px-3 pb-1 text-[10px] font-bold uppercase tracking-[0.18em] text-zinc-500">
              {section.label}
            </div>
            <div className="space-y-1">
              {items.map((n) => (
                <NavItem key={n.to} item={n} onNavigate={onNavigate} />
              ))}
            </div>
          </div>
        );
      })}
    </nav>
  );
}

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const { data: companies = [] } = useQuery({
    queryKey: ["companies"],
    queryFn: async () => (await api.get("/companies")).data,
    staleTime: 30000,
  });
  const activeCid = getActiveCompanyId() || companies.find((c) => c.is_default)?.id || companies[0]?.id || "";
  const active = companies.find((c) => c.id === activeCid);

  const switchCompany = (cid) => {
    setActiveCompanyId(cid);
    qc.invalidateQueries();
    navigate(0);
  };

  const isBottomActive = (to) => location.pathname === to || location.pathname.startsWith(to + "/");

  return (
    <div className="min-h-screen flex bg-zinc-100">
      {/* Desktop Sidebar */}
      <aside className="hidden md:flex md:w-64 bg-white border-r border-zinc-200 flex-col" data-testid="sidebar">
        <div className="px-5 py-5 border-b border-zinc-200">
          <BrandLockup />
        </div>
        <CompanySwitcher companies={companies} activeCid={activeCid} active={active} onSwitch={switchCompany} />
        <DeployReadinessBadge variant="desktop" />
        <NavList />
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
            className="mt-2 w-full flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-zinc-200 hover:bg-zinc-950 hover:text-white transition-colors rounded-sm min-h-[40px] justify-center"
          >
            <LogOut size={14} /> Logout
          </button>
        </div>
      </aside>

      {/* Mobile Drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden" data-testid="mobile-drawer">
          <div
            className="absolute inset-0 bg-zinc-900/60 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-[85%] max-w-[320px] bg-white shadow-2xl flex flex-col animate-in slide-in-from-left">
            <div className="px-5 py-5 border-b border-zinc-200 flex items-center justify-between">
              <BrandLockup compact />
              <button
                onClick={() => setDrawerOpen(false)}
                data-testid="mobile-drawer-close"
                className="w-11 h-11 flex items-center justify-center rounded-sm hover:bg-zinc-100"
                aria-label="Close menu"
              >
                <X size={22} />
              </button>
            </div>
            <CompanySwitcher companies={companies} activeCid={activeCid} active={active} onSwitch={switchCompany} />
            <DeployReadinessBadge variant="desktop" />
            <NavList onNavigate={() => setDrawerOpen(false)} />
            <div className="border-t border-zinc-200 p-3">
              <div className="flex items-center gap-2 px-2 py-2">
                {user?.picture ? (
                  <img src={user.picture} alt="" className="w-9 h-9 rounded-full" />
                ) : (
                  <div className="w-9 h-9 rounded-full bg-zinc-200" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold truncate">{user?.name}</div>
                  <div className="text-[11px] text-zinc-500 truncate">{user?.email}</div>
                </div>
              </div>
              <button
                onClick={logout}
                className="mt-2 w-full flex items-center gap-2 px-3 py-3 text-sm uppercase tracking-wider border border-zinc-200 hover:bg-zinc-950 hover:text-white transition-colors rounded-sm min-h-[44px] justify-center"
              >
                <LogOut size={16} /> Logout
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* Content */}
      <main className="flex-1 min-w-0 flex flex-col">
        {/* Mobile top bar — hamburger + brand + company chip */}
        <div className="md:hidden sticky top-0 z-40 bg-white/95 backdrop-blur border-b border-zinc-200 px-4 py-2.5 flex items-center gap-3">
          <button
            data-testid="mobile-menu-toggle"
            onClick={() => setDrawerOpen(true)}
            className="w-11 h-11 flex items-center justify-center rounded-sm hover:bg-zinc-100 active:bg-zinc-200 -ml-2"
            aria-label="Open menu"
          >
            <Menu size={22} />
          </button>
          <div className="flex-1 min-w-0 flex items-center gap-2">
            <img
              src="/brand/trukvia-mark-64.png"
              srcSet="/brand/trukvia-mark-64.png 1x, /brand/trukvia-mark-128.png 2x"
              alt="TRUKVIA"
              className="h-7 w-auto"
              data-testid="sidebar-brand-mark-topbar"
            />
            <div className="min-w-0">
              <div className="text-[10px] font-black uppercase tracking-[0.2em] text-zinc-950 leading-none">TRUKVIA</div>
              <div className="mt-0.5 text-[9px] text-zinc-500 leading-none">
                <span className="telugu">అకౌంటింగ్</span>
                <span className="mx-1 text-zinc-300">·</span>
                Accounting Suite
              </div>
            </div>
          </div>
          {active && (
            <div className="text-right min-w-0 max-w-[38%]">
              <div className="text-[9px] font-bold uppercase tracking-wider text-zinc-500 leading-none">Company</div>
              <div className="mt-0.5 text-xs font-semibold text-zinc-800 truncate leading-tight">{active.name}</div>
            </div>
          )}
          <DeployReadinessBadge variant="mobile" />
        </div>

        {/* Page content */}
        <div className="p-4 sm:p-6 lg:p-8 max-w-[1400px] mx-auto w-full pb-24 md:pb-8">
          {children}
        </div>

        {/* Mobile bottom nav — 4 daily-driver screens + More */}
        <nav
          className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-white border-t border-zinc-200 shadow-[0_-2px_10px_rgba(0,0,0,0.04)] pb-[env(safe-area-inset-bottom)]"
          data-testid="mobile-bottom-nav"
        >
          <div className="grid grid-cols-5">
            {mobileBottom.map((b) => {
              const active_ = isBottomActive(b.to);
              return (
                <button
                  key={b.to}
                  onClick={() => navigate(b.to)}
                  data-testid={b.testid}
                  className={`relative flex flex-col items-center justify-center gap-0.5 py-2.5 min-h-[56px] transition-colors ${
                    active_ ? "text-zinc-950" : "text-zinc-500 active:bg-zinc-100"
                  }`}
                >
                  <b.icon size={22} strokeWidth={active_ ? 2.25 : 1.75} />
                  <span className={`text-[10px] tracking-wide ${active_ ? "font-bold" : "font-medium"}`}>{b.en}</span>
                  {active_ && (
                    <span
                      className="absolute top-0 h-0.5 w-8 rounded-full"
                      style={{ backgroundColor: "hsl(var(--brand))" }}
                    />
                  )}
                </button>
              );
            })}
            <button
              onClick={() => setDrawerOpen(true)}
              data-testid="bnav-more"
              className="flex flex-col items-center justify-center gap-0.5 py-2.5 min-h-[56px] text-zinc-500 active:bg-zinc-100"
            >
              <MoreHorizontal size={22} strokeWidth={1.75} />
              <span className="text-[10px] tracking-wide font-medium">More</span>
            </button>
          </div>
        </nav>
      </main>
      <AIChatBubble />
    </div>
  );
}
