import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

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
  } catch {}
  return cfg;
});

// If any request returns 401, clear the stored token so the app falls back to Login.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      try { localStorage.removeItem("session_token"); } catch {}
    }
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
