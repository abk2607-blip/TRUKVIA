import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

// De-duplicate the session_id exchange across:
//   - React 18 StrictMode double-invocation
//   - Component remounts (Suspense, fast refresh, route re-entry)
//   - Multiple tabs
//   - Browser back/forward preserving the hash
const CONSUMED_KEY = "consumed_session_ids";

function isConsumed(sid) {
  try {
    const raw = sessionStorage.getItem(CONSUMED_KEY) || "";
    return raw.split(",").includes(sid);
  } catch { return false; }
}
function markConsumed(sid) {
  try {
    const raw = sessionStorage.getItem(CONSUMED_KEY) || "";
    const set = new Set(raw.split(",").filter(Boolean));
    set.add(sid);
    // Keep the list bounded
    const list = [...set].slice(-10);
    sessionStorage.setItem(CONSUMED_KEY, list.join(","));
  } catch {}
}

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const hash = window.location.hash || "";
    const match = hash.match(/session_id=([^&]+)/);
    if (!match) {
      navigate("/", { replace: true });
      return;
    }
    const session_id = decodeURIComponent(match[1]);
    // Immediately strip session_id from the URL so a page reload or
    // browser back-nav doesn't try to re-exchange the same token.
    window.history.replaceState(null, "", window.location.pathname);

    if (isConsumed(session_id)) {
      // Already exchanged in this browser session — just go to dashboard if we
      // already have a valid token, else back to Login.
      try {
        if (localStorage.getItem("session_token")) {
          navigate("/dashboard", { replace: true });
          return;
        }
      } catch {}
      navigate("/", { replace: true });
      return;
    }
    markConsumed(session_id);

    (async () => {
      try {
        const { data } = await api.post("/auth/session", { session_id });
        try { if (data.session_token) localStorage.setItem("session_token", data.session_token); } catch {}
        setUser(data);
        toast.success("Signed in");
        navigate("/dashboard", { replace: true, state: { user: data } });
      } catch (e) {
        // Surface the actual error to help diagnose future failures
        const detail = e?.response?.data?.detail || e?.message || "Unknown error";
        // eslint-disable-next-line no-console
        console.error("Auth exchange failed:", detail, e?.response?.status);
        toast.error(`Sign-in failed: ${detail}`);
        navigate("/", { replace: true });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex items-center justify-center h-screen bg-white" data-testid="auth-callback">
      <div className="text-zinc-600">Signing you in...</div>
    </div>
  );
}
