// Iter97 — Silent Restart Toast.
// Shows a small non-blocking "Refreshing…" pill in the top-right whenever the
// backend is temporarily unreachable (5xx / 404 / network error). Disappears
// automatically the moment /api/auth/health returns 200 again.
import React, { useEffect, useState, useRef } from "react";
import { Loader2 } from "lucide-react";

const HEALTH_URL = (process.env.REACT_APP_BACKEND_URL || "") + "/api/auth/health";

export default function SilentRestartToast() {
  const [restarting, setRestarting] = useState(false);
  const failStreak = useRef(0);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(HEALTH_URL, { cache: "no-store" });
        if (!alive) return;
        if (r.ok) {
          failStreak.current = 0;
          setRestarting(false);
        } else {
          failStreak.current += 1;
          if (failStreak.current >= 2) setRestarting(true);
        }
      } catch {
        if (!alive) return;
        failStreak.current += 1;
        if (failStreak.current >= 2) setRestarting(true);
      }
    };
    // Poll every 6 s; slight jitter avoids sync with query retries.
    const id = setInterval(tick, 6000 + Math.floor(Math.random() * 500));
    tick();
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!restarting) return null;
  return (
    <div
      data-testid="silent-restart-toast"
      className="pointer-events-none fixed top-3 right-3 z-[60] inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-950/90 text-white text-[11px] uppercase tracking-wider font-semibold shadow-lg"
      role="status" aria-live="polite"
    >
      <Loader2 size={12} className="animate-spin" />
      Refreshing…
    </div>
  );
}
