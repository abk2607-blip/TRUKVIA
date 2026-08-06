import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
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

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
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
  } catch {}
  return cfg;
});

// If a request to /auth/me returns 401 the session is truly invalid — clear it.
// For any OTHER endpoint we do NOT clear the token: a transient permission /
// backend error must never silently sign the user out.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    try {
      const status = err?.response?.status;
      const url = (err?.config?.url || "");
      if (status === 401 && url.includes("/auth/me")) {
        localStorage.removeItem("session_token");
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
