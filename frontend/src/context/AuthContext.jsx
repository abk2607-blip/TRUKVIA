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
    // Only call /auth/me when we HAVE a token to avoid spurious 401s that
    // trigger the "clear session" interceptor. Users without a token are
    // simply not logged in — no request needed.
    let hasToken = false;
    try { hasToken = !!localStorage.getItem("session_token"); } catch {}
    if (!hasToken) {
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
      // Iter48 — Only clear the session on an EXPLICIT 401 from /auth/me. Any
      // other error (network, 5xx, timeout, CORS) must keep the cached user
      // intact so a transient backend hiccup never logs the user out.
      if (err?.response?.status === 401) {
        setUser(null);
        try { localStorage.removeItem("session_token"); } catch {}
      }
      // else: keep the current user state (cached from LS) — user stays signed in
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
