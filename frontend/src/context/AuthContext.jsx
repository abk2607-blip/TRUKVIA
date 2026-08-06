import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
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

  const setUser = useCallback((u) => {
    setUserRaw(u);
    try {
      if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
      else localStorage.removeItem(USER_KEY);
    } catch {}
  }, []);

  const checkAuth = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch (err) {
      // Only treat 401 as an actual auth failure. Network/5xx errors must NOT
      // silently sign the user out — keep the cached user so a brief backend
      // hiccup doesn't kick them back to the Login screen.
      if (err?.response?.status === 401) {
        setUser(null);
        try { localStorage.removeItem("session_token"); } catch {}
      }
    } finally {
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
