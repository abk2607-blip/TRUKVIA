import axios from "axios";

// Runtime-derive the backend URL. If the build was compiled with a wrong or
// empty REACT_APP_BACKEND_URL (common on statically-cached preview builds),
// fall back to the sibling ".preview.emergentagent.com" host that owns the
// backend for this project. This way login works on both the dynamic preview
// URL and the Cloudflare-cached ".preview.static.emergentagent.com" URL.
function _resolveBackendUrl() {
  const env = process.env.REACT_APP_BACKEND_URL;
  if (env && /^https?:\/\//.test(env)) return env.replace(/\/+$/, "");
  if (typeof window !== "undefined" && window.location?.hostname) {
    const h = window.location.hostname;
    // Map ".preview.static.emergentagent.com" -> ".preview.emergentagent.com"
    if (h.includes(".preview.static.emergentagent.com")) {
      return `${window.location.protocol}//${h.replace(".preview.static.emergentagent.com", ".preview.emergentagent.com")}`;
    }
  }
  return env || "";
}

const BACKEND_URL = _resolveBackendUrl();
export const API = `${BACKEND_URL}/api`;

const ACTIVE_COMPANY_KEY = "active_company_id";
export const getActiveCompanyId = () => {
  try { return localStorage.getItem(ACTIVE_COMPANY_KEY) || ""; } catch { return ""; }
};
export const setActiveCompanyId = (cid) => {
  try {
    if (cid) localStorage.setItem(ACTIVE_COMPANY_KEY, cid);
    else localStorage.removeItem(ACTIVE_COMPANY_KEY);
  } catch {}
};

// We authenticate via a Bearer token (localStorage `session_token`), so
// requests do NOT need to send cookies. Keeping withCredentials=false keeps
// CORS simple: any origin (including the static preview domain) can hit the
// API without the browser rejecting `Access-Control-Allow-Origin: *`.
export const api = axios.create({
  baseURL: API,
  withCredentials: false,
  // Iter69 — Hard client-side timeout so a stuck request can never leave the
  // UI hanging on "Loading…" forever. Long-running endpoints (LLM insights,
  // PDF generation) may override per-call via `{timeout: N}`.
  timeout: 25000,
});

// Attach Bearer token from localStorage as a fallback for browsers that
// block third-party cookies (Safari/iOS default, Chrome incognito, etc.)
api.interceptors.request.use((cfg) => {
  try {
    const t = localStorage.getItem("session_token");
    if (t) {
      cfg.headers = cfg.headers || {};
      if (!cfg.headers.Authorization) cfg.headers.Authorization = `Bearer ${t}`;
    }
    // Attach active company for multi-company scoping
    const cid = getActiveCompanyId();
    if (cid) {
      cfg.headers = cfg.headers || {};
      if (!cfg.headers["X-Company-Id"]) cfg.headers["X-Company-Id"] = cid;
    }
    // Iter126b — Auto-attach Idempotency-Key for Bucket-B POSTs.
    // The key is generated ONCE per logical request. Retries via the
    // response interceptor (Iter126a Bucket-A retry OR one-shot /auth/me
    // relaunch) re-use `err.config`, which already carries this header —
    // so the same UUID is sent to the server for every retry, letting the
    // backend replay the ORIGINAL result instead of creating a duplicate.
    // The guard `!cfg.headers["Idempotency-Key"]` is critical: it prevents
    // a fresh key from being minted on retry, and also lets a caller pass
    // an explicit key when they need cross-tab or persistent dedup.
    if (_isBucketBPost(cfg)) {
      cfg.headers = cfg.headers || {};
      if (!cfg.headers["Idempotency-Key"]) {
        cfg.headers["Idempotency-Key"] = _newUuid();
      }
    }
  } catch {}
  return cfg;
});

// If a request to /auth/me returns 401 the session is truly invalid — clear it.
// For any OTHER endpoint we do NOT clear the token: a transient permission /
// backend error must never silently sign the user out.
// Iter49 — Also normalise `err.response.data.detail` so callers can safely
// interpolate it into React text nodes. FastAPI/Pydantic v2 returns a raw
// array of {type, loc, msg, input, url} objects on 422, which crashes React
// when rendered directly. We flatten it to a single human string and preserve
// the raw payload under `.detail_raw` for advanced callers.
function _flattenDetail(d) {
  if (d == null) return null;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    const parts = d.slice(0, 3).map((e) => {
      const loc = Array.isArray(e?.loc) ? e.loc.filter((x) => x !== "body").join(".") : "";
      const msg = e?.msg || "invalid";
      return loc ? `${loc}: ${msg}` : msg;
    });
    return `Validation error — ${parts.join("; ")}`;
  }
  if (typeof d === "object") return d.message || d.msg || JSON.stringify(d);
  return String(d);
}

// Iter126 — Endpoint Safety Matrix. See docs: /app/memory/PRD.md.
//
// Bucket A → naturally idempotent → auto-retry on transient 5xx (Iter126a)
// Bucket B → creates / payments / uploads / LR-regenerate → attach an
//            Idempotency-Key so duplicate button-clicks / silent retries
//            never create duplicate rows (Iter126b, this section).
// Bucket C → never auto-retry, never send a key (LLM cost calls, comms,
//            bulk mutations, auth handshakes).
//
// Retry rules (Bucket A)
//   - Method GET / HEAD / OPTIONS  → always retry
//   - Method PUT / PATCH / DELETE  → always retry (REST idempotent contract)
//   - Method POST                  → only retry if URL matches BUCKET_A_POST
//   - Retry only on: network error (no response) OR 502 / 503 / 504
//   - Max 2 attempts after the first (total 3 tries) with backoff 500ms, 1500ms
const BUCKET_A_POST = [
  /\/companies\/[^/]+\/set-default$/,
  /\/auth\/logout$/,
  /\/trips\/lr\/preview$/,
  /\/trips\/bulk-invoice-preflight$/,
  /\/policy-changes\/preview$/,
  /\/vehicles\/bulk-import\/preview$/,
];

// Iter126b — Bucket-B POST whitelist (MUST mirror
// /app/backend/idempotency.py :: BUCKET_B_PATTERNS). Paths here have NO
// `/api` prefix because axios `baseURL` already resolves to `${host}/api`.
export const BUCKET_B_POST = [
  // top-level creates
  /^\/trips$/,
  /^\/companies$/,
  /^\/customers$/,
  /^\/suppliers$/,
  /^\/drivers$/,
  /^\/vehicles$/,
  /^\/invoices$/,
  /^\/products$/,
  /^\/parties$/,
  /^\/team$/,
  /^\/templates$/,
  /^\/fuel$/,
  /^\/expenditure-types$/,
  /^\/saved-trip-filters$/,
  /^\/driver-shortage-policies$/,
  // sub-resource creates
  /^\/customers\/[^/]+\/ship-sites$/,
  /^\/customers\/[^/]+\/add-payment$/,
  /^\/suppliers\/[^/]+\/payments$/,
  /^\/invoices\/[^/]+\/payments$/,
  /^\/drivers\/[^/]+\/ledger$/,
  /^\/drivers\/[^/]+\/ledger\/post-monthly-salary$/,
  /^\/drivers\/[^/]+\/ledger\/settle$/,
  /^\/drivers\/[^/]+\/salary-masters$/,
  /^\/trips\/[^/]+\/supplier-diesel$/,
  /^\/trips\/[^/]+\/supplier-advance$/,
  /^\/trips\/[^/]+\/field-override$/,
  /^\/trips\/[^/]+\/duplicate$/,
  /^\/trips\/from-template\/[^/]+$/,
  /^\/trips\/quick-repeat\/[^/]+$/,
  // uploads
  /^\/files\/upload$/,
  /^\/files\/bulk-upload$/,
  /^\/company\/logo$/,
  // bulk imports
  /^\/trips\/import$/,
  /^\/vehicles\/bulk-import$/,
  // A→B LR regenerate moves
  /^\/trips\/[^/]+\/regenerate-lr$/,
  /^\/trips\/bulk-regenerate-lr$/,
  /^\/trips\/bulk-all-copies-zip$/,
];

const RETRY_DELAYS_MS = [500, 1500];

function _isBucketA(cfg) {
  const method = (cfg?.method || "get").toLowerCase();
  if (method === "get" || method === "head" || method === "options") return true;
  if (method === "put" || method === "patch" || method === "delete") return true;
  if (method === "post") {
    const url = cfg?.url || "";
    return BUCKET_A_POST.some((rx) => rx.test(url));
  }
  return false;
}

export function _isBucketBPost(cfg) {
  if ((cfg?.method || "").toLowerCase() !== "post") return false;
  const url = cfg?.url || "";
  return BUCKET_B_POST.some((rx) => rx.test(url));
}

// RFC-4122 v4 UUID. `crypto.randomUUID` in modern browsers/Node ≥19; a
// getRandomValues-backed fallback covers older Safari. Never falls back to
// `Math.random` — a weak key would silently break per-request uniqueness.
function _newUuid() {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    if (typeof crypto !== "undefined" && crypto.getRandomValues) {
      const b = new Uint8Array(16);
      crypto.getRandomValues(b);
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
  } catch {}
  // Last-resort — timestamp + counter. Not RFC compliant but still unique
  // enough to prevent duplicate-Save within a session. Only reached if the
  // Web Crypto API is entirely missing.
  return `ts-${Date.now()}-${(_newUuid._n = (_newUuid._n || 0) + 1)}`;
}

function _isTransient(err) {
  if (!err?.response) return true; // network error / timeout / DNS
  const s = err.response.status;
  return s === 502 || s === 503 || s === 504;
}

api.interceptors.response.use(
  (r) => r,
  async (err) => {
    try {
      const status = err?.response?.status;
      const url = (err?.config?.url || "");
      const detail = err?.response?.data?.detail || err?.response?.data?.detail_raw;
      const detailStr = typeof detail === "string" ? detail.toLowerCase() : "";

      // Iter126a — Transient retry for Bucket A endpoints.
      if (err?.config && _isBucketA(err.config) && _isTransient(err)) {
        err.config._retryCount = err.config._retryCount || 0;
        if (err.config._retryCount < RETRY_DELAYS_MS.length) {
          const delay = RETRY_DELAYS_MS[err.config._retryCount];
          err.config._retryCount += 1;
          await new Promise((r) => setTimeout(r, delay));
          try {
            return await api.request(err.config);
          } catch (retryErr) {
            err = retryErr;
          }
        }
      }
      // Iter102 — Hardened sign-out trigger.
      // Only clear the token when the server EXPLICITLY confirms the session
      // is dead — never on a generic 401, and never before a one-shot retry
      // (backend restart / transient network hiccup should not sign the user
      // out). Two guards:
      //   1. Detail must be one of: "invalid session", "session expired",
      //      "not authenticated" — anything else (permission errors, RBAC,
      //      wrong-tenant, missing header) leaves the token intact.
      //   2. Only trigger on /auth/me — the canonical session-health probe.
      const isAuthMe = url.includes("/auth/me");
      const isSessionDead = ["invalid session", "session expired", "not authenticated"]
        .some((s) => detailStr.includes(s));
      if (status === 401 && isAuthMe && isSessionDead && !err.config._retriedAuthMe) {
        // One-shot retry after a short cushion — protects against transient
        // 401s during a backend restart or a race on the demo-token ensure step.
        err.config._retriedAuthMe = true;
        await new Promise((r) => setTimeout(r, 800));
        try {
          return await api.request(err.config);
        } catch (retryErr) {
          const rStatus = retryErr?.response?.status;
          const rDetail = retryErr?.response?.data?.detail;
          const rDetailStr = typeof rDetail === "string" ? rDetail.toLowerCase() : "";
          const stillDead = ["invalid session", "session expired", "not authenticated"]
            .some((s) => rDetailStr.includes(s));
          if (rStatus === 401 && stillDead) {
            // Confirmed dead session — safe to clear now.
            localStorage.removeItem("session_token");
          }
          err = retryErr;
        }
      }
      // Normalise error detail so React text nodes never crash
      if (err?.response?.data && err.response.data.detail !== undefined) {
        err.response.data.detail_raw = err.response.data.detail;
        err.response.data.detail = _flattenDetail(err.response.data.detail);
      }
    } catch {}
    return Promise.reject(err);
  }
);

// Helpers
export const fmtCurrency = (n) => {
  const v = Number(n || 0);
  return `₹ ${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const fmtNum = (n, d = 2) => {
  const v = Number(n || 0);
  return v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
};

export const fmtDate = (iso) => {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
};


// Iter49 — Safely stringify any error payload for toast/UI display.
// FastAPI/Pydantic v2 returns validation errors as an ARRAY of
// {type, loc, msg, input, url} objects. Passing that array to a React text
// node crashes with "Objects are not valid as a React child".
// This helper always returns a human-readable single string.
export const errMsg = (err, fallback = "Failed") => {
  try {
    const d = err?.response?.data?.detail;
    if (!d) return err?.message || fallback;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      // Pydantic v2 validation errors — surface the first field + msg
      const parts = d.slice(0, 3).map((e) => {
        const loc = Array.isArray(e?.loc) ? e.loc.filter((x) => x !== "body").join(".") : "";
        const msg = e?.msg || "invalid";
        return loc ? `${loc}: ${msg}` : msg;
      });
      return `Validation error — ${parts.join("; ")}`;
    }
    if (typeof d === "object") return d.message || d.msg || JSON.stringify(d);
    return String(d);
  } catch {
    return fallback;
  }
};
