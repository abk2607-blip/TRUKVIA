import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/api";

/*
 * Iter106b · Auth Bootstrap Resilience
 * ------------------------------------
 * Five layered guarantees so the UI is NEVER permanently stuck on a loading
 * spinner:
 *
 *  1. Hard 6-second bootstrap timeout — regardless of what /auth/me does,
 *     `loading` flips to false within 6 s. If we don't know the state yet
 *     we still render (Login / cached user) instead of a spinner.
 *
 *  2. Retry with exponential backoff on 5xx or network errors — 3 attempts
 *     at 400 ms, 900 ms, 2 s. Silently covers the backend-boot window
 *     (0-15 s) and short pod restarts.
 *
 *  3. Visible "Reconnecting…" / "Server unreachable · Retry" state exposed
 *     via `authError` and `retryBootstrap()` for the Login screen to
 *     render a clear recovery action.
 *
 *  4. Strict error-class separation:
 *       401 (invalid session / session expired) → OAuth relaunch
 *       401 (not authenticated / RBAC / permission) → no relaunch
 *       5xx + network + timeout                   → NEVER relaunch OAuth,
 *                                                   NEVER drop cached user
 *
 *  5. Cached user preserved during ANY transient server issue; cleared
 *     ONLY on a confirmed session-dead 401 or on explicit logout.
 */

const AuthContext = createContext(null);
const USER_KEY = "auth_user";

// Tunables — kept as module constants for testability.
const BOOTSTRAP_HARD_TIMEOUT_MS = 6000;
const RETRY_DELAYS_MS = [400, 900, 2000]; // 3 attempts = initial + 2 retries
const PER_ATTEMPT_TIMEOUT_MS = 4500;      // < axios default 25 s; bounds each try

function readCachedUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function isNetworkOrServerError(err) {
  // No response at all → network / DNS / CORS / offline / ingress 502 boot.
  if (!err?.response) return true;
  const s = err.response.status;
  return s >= 500 && s <= 599;
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

export const AuthProvider = ({ children }) => {
  // Optimistic user hydration — a valid cached session doesn't briefly
  // flash the Login screen while /auth/me is in flight.
  const [user, setUserRaw] = useState(readCachedUser);
  const [loading, setLoading] = useState(true);
  // authError = { code: 'reconnecting' | 'unreachable', message: string } | null
  const [authError, setAuthError] = useState(null);
  const inflight = useRef(false);
  const hardTimeoutRef = useRef(null);
  const bootstrapAttemptRef = useRef(0);

  const setUser = useCallback((u) => {
    setUserRaw(u);
    try {
      if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
      else localStorage.removeItem(USER_KEY);
    } catch {}
  }, []);

  const _oneAttempt = useCallback(async () => {
    // Per-attempt timeout via AbortController — never rely solely on axios.
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), PER_ATTEMPT_TIMEOUT_MS);
    try {
      const { data } = await api.get("/auth/me", { signal: ctrl.signal });
      return { ok: true, data };
    } catch (err) {
      return { ok: false, err };
    } finally {
      clearTimeout(t);
    }
  }, []);

  const checkAuth = useCallback(async () => {
    // Empty state — no session hint whatsoever → land on Login cleanly.
    // This is the ONLY code path that finishes bootstrap without hitting
    // /auth/me. It matches the correct first-time-visitor / clean-logout
    // behaviour and cannot itself hang.
    let hasToken = false;
    let hadCachedUser = false;
    try { hasToken = !!localStorage.getItem("session_token"); } catch {}
    try { hadCachedUser = !!localStorage.getItem(USER_KEY); } catch {}
    if (!hasToken && !hadCachedUser && !document.cookie.includes("session_token=")) {
      setUser(null);
      setLoading(false);
      setAuthError(null);
      return;
    }

    if (inflight.current) return; // dedupe concurrent bootstrap calls
    inflight.current = true;
    bootstrapAttemptRef.current += 1;
    const myAttempt = bootstrapAttemptRef.current;

    // Layer 1 — Hard 6 s ceiling. If we still don't know by then, we
    // stop showing the spinner. Cached user (if any) stays; the Login
    // screen will render its own "reconnecting" chip.
    if (hardTimeoutRef.current) clearTimeout(hardTimeoutRef.current);
    hardTimeoutRef.current = setTimeout(() => {
      if (bootstrapAttemptRef.current !== myAttempt) return;
      setLoading(false);
      setAuthError((prev) => prev || {
        code: "reconnecting",
        message: "Still checking your session…",
      });
    }, BOOTSTRAP_HARD_TIMEOUT_MS);

    let lastErr = null;
    for (let i = 0; i < RETRY_DELAYS_MS.length; i++) {
      // Show "Reconnecting…" chip from the 2nd attempt onwards.
      if (i > 0) {
        setAuthError({ code: "reconnecting",
                       message: `Reconnecting to server (${i + 1}/${RETRY_DELAYS_MS.length})…` });
      }
      const { ok, data, err } = await _oneAttempt();
      if (ok) {
        setUser(data);
        setLoading(false);
        setAuthError(null);
        inflight.current = false;
        if (hardTimeoutRef.current) { clearTimeout(hardTimeoutRef.current); hardTimeoutRef.current = null; }
        return;
      }
      lastErr = err;

      // 401 → decide immediately, no retries.
      const status = err?.response?.status;
      if (status === 401) {
        const rawDetail = err?.response?.data?.detail || err?.response?.data?.detail_raw;
        const detailStr = typeof rawDetail === "string" ? rawDetail.toLowerCase() : "";
        // Layer 4a — only true session-dead relaunches OAuth. "Not
        // authenticated" alone (fresh visitor / RBAC / no cookie yet) is
        // deliberately excluded — the empty-hint short-circuit above
        // already handles that case.
        const isSessionDead = ["invalid session", "session expired"].some(
          (s) => detailStr.includes(s)
        );
        if (isSessionDead) {
          try { localStorage.removeItem("session_token"); } catch {}
          try { localStorage.removeItem(USER_KEY); } catch {}
          setUser(null);
          setLoading(false);
          setAuthError(null);
          inflight.current = false;
          if (hardTimeoutRef.current) { clearTimeout(hardTimeoutRef.current); hardTimeoutRef.current = null; }
          const onLoginPage = window.location?.pathname === "/";
          const inCallback = window.location?.hash?.includes("session_id=");
          if (!onLoginPage && !inCallback) {
            // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
            const redirectUrl = window.location.origin + "/dashboard";
            window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
          }
          return;
        }
        // Non-session-dead 401 (RBAC / permission / "not authenticated")
        // — stop retrying, don't drop cached user, don't relaunch OAuth.
        break;
      }

      // Layer 4b — retry only on 5xx / network / timeout. Anything else
      // (4xx, malformed, etc.) → stop retrying immediately.
      if (!isNetworkOrServerError(err)) break;

      // Backoff before next attempt (unless this was the last one).
      if (i < RETRY_DELAYS_MS.length - 1) {
        await sleep(RETRY_DELAYS_MS[i]);
      }
    }

    // All retries exhausted or non-retryable error. Decide final state.
    setLoading(false);
    inflight.current = false;
    if (hardTimeoutRef.current) { clearTimeout(hardTimeoutRef.current); hardTimeoutRef.current = null; }

    if (isNetworkOrServerError(lastErr)) {
      // Layer 3 — surfaced to Login screen as a manual Retry action.
      // Cached user PRESERVED (Layer 5) so a mid-session backend blip
      // never signs the user out.
      setAuthError({
        code: "unreachable",
        message: "Server is unreachable. Retry?",
      });
    } else {
      // 401 non-session-dead or unexpected client error — no visible
      // reconnect banner needed; the app already has cached user, and
      // downstream API calls will surface the real error.
      setAuthError(null);
    }
  }, [setUser, _oneAttempt]);

  const retryBootstrap = useCallback(() => {
    setAuthError(null);
    setLoading(true);
    // Reset dedupe guard — user-initiated retry always fires.
    inflight.current = false;
    checkAuth();
  }, [checkAuth]);

  useEffect(() => {
    // Skip /me if OAuth callback is running (AuthCallback.jsx owns that).
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    checkAuth();
    // Iter48 — Periodic session heartbeat every 5 min. If a stale token
    // has expired server-side during a long form-entry session we surface
    // it early instead of the user losing typed data on submit.
    const iv = setInterval(() => {
      try { if (localStorage.getItem("session_token")) checkAuth(); } catch {}
    }, 5 * 60 * 1000);
    return () => {
      clearInterval(iv);
      if (hardTimeoutRef.current) clearTimeout(hardTimeoutRef.current);
    };
  }, [checkAuth]);

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    try {
      localStorage.removeItem("session_token");
      localStorage.removeItem(USER_KEY);
    } catch {}
    setUser(null);
    setAuthError(null);
    window.location.href = "/";
  };

  return (
    <AuthContext.Provider value={{
      user, setUser, loading, checkAuth, logout,
      authError, retryBootstrap,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
