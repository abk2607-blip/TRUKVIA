import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/api";

const AuthContext = createContext(null);

const USER_KEY = "auth_user";

function readCachedUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export const AuthProvider = ({ children }) => {
  // Optimistic user hydration from localStorage cache so a valid session
  // doesn't briefly redirect to the Login screen while /auth/me is in flight.
  const [user, setUserRaw] = useState(readCachedUser);
  const [loading, setLoading] = useState(true);
  const inflight = useRef(false);

  const setUser = useCallback((u) => {
    setUserRaw(u);
    try {
      if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
      else localStorage.removeItem(USER_KEY);
    } catch {}
  }, []);

  const checkAuth = useCallback(async () => {
    // Iter110 fix — Do NOT gate /auth/me on localStorage.session_token. The
    // OAuth callback stores the token primarily as a browser cookie; after a
    // power-off / power-on, session-scoped cookies may be gone but a valid
    // persistent cookie can still exist, and vice-versa. The backend accepts
    // BOTH sources (cookie OR Bearer header). We only skip /auth/me when we
    // have literally nothing — neither a token nor a cached user hint —
    // because in that case there is no session to recover anyway.
    let hasToken = false;
    let hadCachedUser = false;
    try { hasToken = !!localStorage.getItem("session_token"); } catch {}
    try { hadCachedUser = !!localStorage.getItem(USER_KEY); } catch {}
    // Empty state — no session at all. Show Login cleanly. This is the ONLY
    // path that lands the user on Login without an OAuth recovery attempt,
    // and it is the correct behaviour (first-time visitor or explicit logout).
    if (!hasToken && !hadCachedUser && !document.cookie.includes("session_token=")) {
      setUser(null);
      setLoading(false);
      return;
    }
    if (inflight.current) return; // dedupe concurrent calls
    inflight.current = true;
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch (err) {
      // Iter106 — On a hard, confirmed session-dead 401 from /auth/me, auto
      // relaunch the Google OAuth flow so the user never lands on a dead
      // Login screen. Only two error strings from the server are treated as
      // "session dead": "invalid session" and "session expired". Any other
      // 401 (permission errors, RBAC, wrong-tenant) is left alone — cached
      // user stays and downstream calls surface the real error. Any non-401
      // (network, 5xx, timeout, CORS) also leaves cached user intact.
      const status = err?.response?.status;
      const rawDetail = err?.response?.data?.detail || err?.response?.data?.detail_raw;
      const detailStr = typeof rawDetail === "string" ? rawDetail.toLowerCase() : "";
      // Iter110 — Only true session-dead errors trigger the OAuth relaunch.
      // "Not authenticated" is deliberately NOT in this list — the top-level
      // hint short-circuit already handles empty state (fresh visitor / clean
      // logout). Widening the list would auto-redirect fresh visitors before
      // they see the Login screen, breaking the RBAC/deep-link flows and the
      // iter106 regression guard.
      const isSessionDead = ["invalid session", "session expired"].some(
        (s) => detailStr.includes(s)
      );
      if (status === 401 && isSessionDead) {
        try { localStorage.removeItem("session_token"); } catch {}
        try { localStorage.removeItem(USER_KEY); } catch {}
        setUser(null);
        const onLoginPage = window.location?.pathname === "/";
        const inCallback = window.location?.hash?.includes("session_id=");
        if (!onLoginPage && !inCallback) {
          // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
          const redirectUrl = window.location.origin + "/dashboard";
          window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
          return;
        }
      }
      // else: keep cached user (transient error) — user stays signed in
    } finally {
      inflight.current = false;
      setLoading(false);
    }
  }, [setUser]);

  useEffect(() => {
    // Skip /me if OAuth callback is running
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    checkAuth();
    // Iter48 — Periodic session heartbeat every 5 min. If a stale token has
    // expired server-side during a long form-entry session we surface it
    // early with a toast instead of the user losing typed data on submit.
    const iv = setInterval(() => {
      try { if (localStorage.getItem("session_token")) checkAuth(); } catch {}
    }, 5 * 60 * 1000);
    return () => clearInterval(iv);
  }, [checkAuth]);

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    try {
      localStorage.removeItem("session_token");
      localStorage.removeItem(USER_KEY);
    } catch {}
    setUser(null);
    window.location.href = "/";
  };

  return (
    <AuthContext.Provider value={{ user, setUser, loading, checkAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
