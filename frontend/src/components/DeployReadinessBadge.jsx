/**
 * Iter128 · Deploy Readiness Badge
 * --------------------------------
 * A compact top-nav pill that mirrors /api/admin/deploy-readiness.
 *   States → Ready · Checking… · Not ready · Offline
 *   Visibility → Owner + Admin + Manager only (frontend gate)
 *   Poll → every 60s via TanStack Query, paused when the tab is hidden.
 *   Click → popover with status + checked_at + elapsed_s + exit_code +
 *           "See History" link to the existing /admin/deploy-history page.
 *
 * Locked scope for this MVP:
 *   • No "Run Check Now" button.
 *   • No new API endpoints — reuses /api/admin/deploy-readiness only.
 *   • Compact icon-only variant used inside the mobile top bar.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, AlertCircle, Loader2, WifiOff, ChevronDown } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/context/AuthContext";

const POLL_MS = 60_000;

// Sentinels returned by the query fn so we can distinguish states without
// throwing / retrying uselessly.
const OFFLINE = { status: "__offline__" };
const FORBIDDEN = { status: "__forbidden__" };

function humaniseAgo(iso) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (!t || Number.isNaN(t)) return "—";
  const diff = Math.max(0, Date.now() - t);
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

function resolveState(query) {
  if (query.isLoading && !query.data) return "checking";
  const d = query.data;
  if (!d) return "checking";
  if (d === OFFLINE || d.status === "__offline__") return "offline";
  if (d.status === "pass") return "ready";
  if (d.status === "fail") return "not-ready";
  return "checking"; // "unknown" from API
}

const STATE_META = {
  ready:      { label: "Ready",       dot: "bg-emerald-500", text: "text-emerald-800", ring: "border-emerald-300 bg-emerald-50 hover:bg-emerald-100", Icon: CheckCircle2 },
  checking:   { label: "Checking…",   dot: "bg-amber-500",   text: "text-amber-800",   ring: "border-amber-300 bg-amber-50 hover:bg-amber-100",     Icon: Loader2 },
  "not-ready":{ label: "Not ready",   dot: "bg-rose-500",    text: "text-rose-800",    ring: "border-rose-300 bg-rose-50 hover:bg-rose-100",         Icon: AlertCircle },
  offline:    { label: "Offline",     dot: "bg-zinc-400",    text: "text-zinc-700",    ring: "border-zinc-300 bg-zinc-50 hover:bg-zinc-100",         Icon: WifiOff },
};

const STATE_HELP = {
  ready:      "All checks passing",
  checking:   "First check in progress (starts ~30 s after boot)",
  "not-ready":"One or more checks failing",
  offline:    "Can't reach the check server right now",
};


function usePageVisibility() {
  const [visible, setVisible] = useState(
    typeof document === "undefined" ? true : !document.hidden
  );
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

/**
 * Popover — shown beneath the badge on desktop, and as a small floating
 * card on mobile. Closes on outside click, Esc, and route change.
 */
function Popover({ state, data, onClose, anchorTestId }) {
  const ref = useRef(null);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    const onClick = (e) => {
      if (!ref.current) return;
      if (!ref.current.contains(e.target)) onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [onClose]);

  const meta = STATE_META[state];
  const isOffline = state === "offline";
  const isUnknown = state === "checking" && (!data || data.status === "unknown");
  const checkedAt = data?.checked_at || null;
  const elapsedS = typeof data?.elapsed_s === "number" ? `${data.elapsed_s.toFixed(1)}s` : "—";
  const exitCode = typeof data?.exit_code === "number" ? String(data.exit_code) : "—";

  return (
    <div
      ref={ref}
      data-testid="deploy-badge-popover"
      role="dialog"
      aria-label="Deploy readiness details"
      className="absolute z-50 mt-2 w-72 rounded-sm border border-zinc-950 bg-white shadow-lg"
    >
      <div className="px-4 py-3 border-b border-zinc-200 flex items-center gap-2">
        <span className={`inline-block w-2.5 h-2.5 rounded-full ${meta.dot}`} />
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Deploy Readiness</div>
          <div className={`font-bold text-sm ${meta.text}`}>{meta.label}</div>
        </div>
      </div>
      <div className="px-4 py-3 space-y-2 text-xs">
        <p className="text-zinc-700 leading-snug">{STATE_HELP[state]}</p>

        {isOffline || isUnknown ? null : (
          <dl className="border border-zinc-200 rounded-sm divide-y divide-zinc-200">
            <div className="flex px-3 py-1.5">
              <dt className="w-28 text-[10px] uppercase tracking-wider font-bold text-zinc-500">Checked</dt>
              <dd
                className="flex-1 font-mono text-[11px] text-zinc-900"
                title={checkedAt || ""}
                data-testid="deploy-badge-checked-at"
              >
                {humaniseAgo(checkedAt)}
              </dd>
            </div>
            <div className="flex px-3 py-1.5">
              <dt className="w-28 text-[10px] uppercase tracking-wider font-bold text-zinc-500">Elapsed</dt>
              <dd className="flex-1 font-mono text-[11px] text-zinc-900" data-testid="deploy-badge-elapsed">
                {elapsedS}
              </dd>
            </div>
            <div className="flex px-3 py-1.5">
              <dt className="w-28 text-[10px] uppercase tracking-wider font-bold text-zinc-500">Exit Code</dt>
              <dd className="flex-1 font-mono text-[11px] text-zinc-900" data-testid="deploy-badge-exit-code">
                {exitCode}
              </dd>
            </div>
          </dl>
        )}

        {isUnknown && data?.message && (
          <p className="text-[11px] italic text-zinc-500" data-testid="deploy-badge-unknown-hint">
            {data.message}
          </p>
        )}
      </div>
      <div className="px-4 py-2 border-t border-zinc-200 flex justify-end">
        <Link
          to="/admin/deploy-history"
          onClick={onClose}
          data-testid="deploy-badge-see-history"
          className="text-[11px] uppercase tracking-wider font-bold text-zinc-950 hover:underline"
          aria-describedby={anchorTestId}
        >
          See History →
        </Link>
      </div>
    </div>
  );
}


export default function DeployReadinessBadge({ variant = "desktop" }) {
  const { user } = useAuth();
  const visible = usePageVisibility();
  const [open, setOpen] = useState(false);

  // Backend is the authoritative role gate — the /api/admin/deploy-readiness
  // endpoint returns 403 for accountant / viewer. We simply try the call and
  // hide the badge if the server says forbidden.
  const query = useQuery({
    queryKey: ["deploy-readiness"],
    enabled: !!user && visible,
    queryFn: async () => {
      try {
        const r = await api.get("/admin/deploy-readiness");
        return r.data;
      } catch (err) {
        const status = err?.response?.status;
        // Role gate: back-end says this user isn't allowed — hide the badge.
        if (status === 403) return FORBIDDEN;
        // 401 handled by AuthContext; treat as not-eligible for this widget.
        if (status === 401) return FORBIDDEN;
        // Network error or 5xx → surface as offline; don't spam retries.
        if (!err?.response || (typeof status === "number" && status >= 500)) {
          return OFFLINE;
        }
        return OFFLINE;
      }
    },
    refetchInterval: visible ? POLL_MS : false,
    refetchIntervalInBackground: false,
    retry: 1,
    staleTime: 30_000,
  });

  const forbidden = query.data === FORBIDDEN || query.data?.status === "__forbidden__";
  const state = useMemo(
    () => resolveState(query),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query.data, query.isLoading],
  );

  // Hide the badge entirely once the server confirms the user is not allowed.
  if (!user || forbidden) return null;

  const meta = STATE_META[state];
  const StatusIcon = meta.Icon;
  const isSpin = state === "checking";

  // Compact icon-only variant for the mobile top bar.
  if (variant === "mobile") {
    return (
      <div className="relative">
        <button
          type="button"
          data-testid="deploy-badge-root"
          aria-label={`Deploy readiness: ${meta.label}`}
          onClick={() => setOpen((v) => !v)}
          className={`inline-flex items-center justify-center w-9 h-9 rounded-sm border ${meta.ring} transition-colors`}
        >
          <StatusIcon
            size={16}
            className={`${meta.text} ${isSpin ? "animate-spin" : ""}`}
            strokeWidth={2}
          />
          <span className="sr-only" data-testid="deploy-badge-status">{state}</span>
        </button>
        {open && (
          <div className="absolute right-0 top-full">
            <Popover state={state} data={query.data} onClose={() => setOpen(false)} anchorTestId="deploy-badge-root" />
          </div>
        )}
      </div>
    );
  }

  // Desktop pill — full-width row under CompanySwitcher.
  return (
    <div className="px-4 py-3 border-b border-zinc-200 relative">
      <div className="text-[10px] uppercase tracking-wider font-bold text-zinc-500 flex items-center gap-1">
        Deploy Readiness
      </div>
      <button
        type="button"
        data-testid="deploy-badge-root"
        aria-label={`Deploy readiness: ${meta.label}`}
        onClick={() => setOpen((v) => !v)}
        className={`mt-1 w-full inline-flex items-center gap-2 border px-2.5 py-2 rounded-sm text-xs font-semibold min-h-[40px] transition-colors ${meta.ring} ${meta.text}`}
      >
        <StatusIcon size={14} className={isSpin ? "animate-spin" : ""} strokeWidth={2} />
        <span className="flex-1 text-left" data-testid="deploy-badge-status">{meta.label}</span>
        <ChevronDown size={12} className="opacity-60" />
      </button>
      {open && (
        <Popover state={state} data={query.data} onClose={() => setOpen(false)} anchorTestId="deploy-badge-root" />
      )}
    </div>
  );
}
