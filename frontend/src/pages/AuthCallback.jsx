import React, { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const hash = location.hash || window.location.hash;
    const match = hash.match(/session_id=([^&]+)/);
    if (!match) {
      navigate("/", { replace: true });
      return;
    }
    const session_id = decodeURIComponent(match[1]);
    window.history.replaceState(null, "", window.location.pathname);

    (async () => {
      try {
        const { data } = await api.post("/auth/session", { session_id });
        // Persist token for Bearer fallback (cookies may be blocked in Safari/iOS)
        try { if (data.session_token) localStorage.setItem("session_token", data.session_token); } catch {}
        setUser(data);
        toast.success("Signed in");
        navigate("/dashboard", { replace: true, state: { user: data } });
      } catch (e) {
        toast.error("Sign-in failed");
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
