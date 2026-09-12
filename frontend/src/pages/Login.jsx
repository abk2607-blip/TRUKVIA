import React from "react";
import { useAuth } from "@/context/AuthContext";
import { Navigate } from "react-router-dom";
import { ShieldCheck, TrendingUp, Landmark, Loader2, RefreshCw, WifiOff } from "lucide-react";

const HERO_IMG = "/images/bitumen-tanker-hero.jpg";

export default function Login() {
  const { user, loading, authError, retryBootstrap } = useAuth();

  // Iter106b — Only show the loading spinner while the bootstrap is BOTH
  // still in-flight AND has no diagnostic state yet. The hard 6 s ceiling
  // in AuthContext guarantees `loading` flips to false regardless, so we
  // can never be trapped here permanently.
  if (loading && !authError) {
    return (
      <div className="flex flex-col items-center justify-center h-screen text-zinc-500 gap-3"
           data-testid="auth-bootstrap-loading">
        <Loader2 className="animate-spin" size={22} />
        <div className="text-sm">Checking your session…</div>
      </div>
    );
  }
  if (user) return <Navigate to="/dashboard" replace />;

  const handleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen grid md:grid-cols-2 bg-white" data-testid="login-page">
      {/* Left brand wall — Iter150E · Option A · Clean & Clear.
          The truck hero remains visible in the lower half of the panel
          via a masked fade, but never dominates the TRUKVIA lock-up. */}
      <div
        className="relative hidden md:flex flex-col overflow-hidden bg-white"
        data-testid="login-brand-wall"
      >
        {/* Subtle ember-tinted top glow to keep the panel warm without
            invoking a dark-mode surface. */}
        <div
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-1/2 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse at 50% -20%, rgba(253,120,0,0.10), rgba(253,120,0,0) 65%)",
          }}
        />
        {/* Truck hero — mounted at the bottom, height-clamped and
            softly faded into the panel background at the top so the
            TRUKVIA logo above is never overpowered. */}
        <div className="absolute inset-x-0 bottom-0 h-[52%] pointer-events-none">
          <img
            src={HERO_IMG}
            alt="Bitumen tanker on Indian highway"
            className="w-full h-full object-cover object-center"
            style={{
              WebkitMaskImage:
                "linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.35) 22%, rgba(0,0,0,0.85) 55%, black 100%)",
              maskImage:
                "linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.35) 22%, rgba(0,0,0,0.85) 55%, black 100%)",
            }}
          />
          {/* Warm sunset wash preserved on the darker truck band so
              the ember token feels earned, not decorative. */}
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background:
                "linear-gradient(to top, rgba(253,120,0,0.10) 0%, rgba(253,120,0,0) 55%)",
            }}
          />
        </div>

        {/* Content column */}
        <div className="relative z-10 flex flex-1 flex-col justify-between px-12 pt-14 pb-10">
          <div>
            {/* Brand lock-up — the raster derivative is the authoritative
                trademark artwork; TM + geometry preserved verbatim. */}
            <img
              src="/brand/trukvia-login-mark.png"
              alt="TRUKVIA — Trademark"
              className="h-20 w-auto"
              data-testid="login-brand-mark"
            />
            <div className="mt-3 flex items-center gap-3">
              <span
                aria-hidden="true"
                className="h-[2px] w-10 rounded-full"
                style={{ backgroundColor: "#FD7800" }}
              />
              <span className="text-[11px] uppercase tracking-[0.32em] font-bold text-zinc-500">
                Accounting Suite
              </span>
            </div>

            {/* Brand message — zinc-950 heading with a single ember
                emphasis mark, matching the "Built for …" direction. */}
            <h1 className="mt-10 text-[42px] leading-[1.05] font-black tracking-tight text-zinc-950">
              Built for<br />
              Bitumen Transporters<span style={{ color: "#FD7800" }}>.</span>
            </h1>
            <p className="mt-5 max-w-md text-sm text-zinc-600 leading-relaxed">
              GST Invoicing &nbsp;·&nbsp; Trip Logs &nbsp;·&nbsp; Expense Tracking
              <br />
              Receivables &nbsp;·&nbsp; Payables &nbsp;·&nbsp; Financial Control
            </p>
          </div>

          {/* Pill row — three restrained capability chips (Option A
              bottom rail) rendered on translucent white so they sit
              cleanly over the truck's fade band. */}
          <div className="relative">
            <div className="grid grid-cols-3 gap-3 max-w-md">
              <Pill icon={ShieldCheck} label="Reliable Operations" />
              <Pill icon={Landmark}    label="Accurate Accounting" />
              <Pill icon={TrendingUp}  label="Stronger Business" />
            </div>
            <div className="mt-6 flex items-center gap-3">
              <span
                aria-hidden="true"
                className="h-[2px] w-10 rounded-full"
                style={{ backgroundColor: "#FD7800" }}
              />
              <span className="text-[10px] uppercase tracking-[0.28em] font-bold text-zinc-500">
                Keep the wheels of business moving
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="text-[11px] uppercase tracking-[0.2em] font-bold text-zinc-500">Sign In</div>
          <h2 className="mt-2 text-4xl font-black tracking-tight text-zinc-950">
            <span className="telugu">స్వాగతం</span>
            <span className="text-zinc-400"> / Welcome</span>
          </h2>
          <p className="mt-3 text-sm text-zinc-600">
            <span className="telugu">మీ Google అకౌంట్‌తో సైన్ ఇన్ చేయండి</span>
            <br />
            <span className="text-zinc-500 text-xs">Sign in with your Google account to continue.</span>
          </p>

          {/* Iter106b — Visible auth-bootstrap status chip. Never a black-
              box spinner; the user always has either a working Sign-In
              action or an explicit Retry. */}
          {authError && (
            <div
              data-testid={`auth-status-${authError.code}`}
              className={`mt-6 border p-3 flex items-start gap-3 ${
                authError.code === "unreachable"
                  ? "bg-rose-50 border-rose-300 text-rose-900"
                  : "bg-amber-50 border-amber-300 text-amber-900"
              }`}
            >
              {authError.code === "unreachable"
                ? <WifiOff size={16} className="mt-0.5 flex-shrink-0" />
                : <Loader2 size={16} className="mt-0.5 flex-shrink-0 animate-spin" />}
              <div className="flex-1 min-w-0">
                <div className="text-[11px] uppercase tracking-widest font-bold">
                  {authError.code === "unreachable" ? "Server Unreachable" : "Reconnecting"}
                </div>
                <div className="text-xs mt-0.5">{authError.message}</div>
              </div>
              {authError.code === "unreachable" && (
                <button
                  data-testid="auth-retry-btn"
                  onClick={retryBootstrap}
                  className="text-[11px] uppercase tracking-widest font-bold px-2 py-1 border border-rose-600 text-rose-700 hover:bg-rose-100 inline-flex items-center gap-1"
                >
                  <RefreshCw size={12} /> Retry
                </button>
              )}
            </div>
          )}

          <button
            data-testid="google-login-button"
            onClick={handleLogin}
            className="mt-8 w-full inline-flex items-center justify-center gap-3 px-4 py-3 bg-zinc-950 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-zinc-950 hover:bg-white hover:text-zinc-950 transition-colors"
          >
            <GoogleIcon /> Continue with Google
          </button>

          {/* Iter106/130 — Demo-login button is fail-secure hidden in
              production. Two build-time flags must BOTH be "1":
                REACT_APP_IS_PREVIEW_ENV=1  (environment gate — absent in prod)
                REACT_APP_ENABLE_DEMO_LOGIN=1 (feature toggle within preview)
              Any real production build omits IS_PREVIEW_ENV, so the button
              is not even present in the shipped JS bundle. The demo token
              is fetched at runtime from POST /api/auth/demo-login — never
              baked into the frontend source. */}
          {process.env.REACT_APP_IS_PREVIEW_ENV === "1" &&
           process.env.REACT_APP_ENABLE_DEMO_LOGIN === "1" && (
            <>
              <div className="relative my-4">
                <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-zinc-200"></div></div>
                <div className="relative flex justify-center"><span className="bg-white px-2 text-[10px] uppercase tracking-widest text-zinc-500">or</span></div>
              </div>
              <button
                data-testid="demo-login-button"
                onClick={async () => {
                  try {
                    const { data } = await (await import("@/api")).api.post("/auth/demo-login");
                    localStorage.setItem("session_token", data.session_token);
                    localStorage.setItem("auth_user", JSON.stringify({
                      user_id: data.user_id, email: data.email, name: data.name, picture: data.picture,
                    }));
                    window.location.href = "/dashboard";
                  } catch (e) {
                    console.error("Demo login endpoint failed:", e);
                  }
                }}
                className="w-full inline-flex items-center justify-center gap-2 px-4 py-3 bg-amber-500 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-amber-500 hover:bg-amber-600 transition-colors"
              >
                Continue as Demo — Skip Login
              </button>
              <p className="mt-1 text-[10px] text-zinc-400 text-center">Dev/QA only — hidden in production builds</p>
            </>
          )}

          <div className="mt-8 border-t border-zinc-200 pt-4">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Compliance</div>
            <div className="mt-1 text-xs text-zinc-600">GST 5% RCM · HSN 996791 · Andhra Pradesh format</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Pill({ icon: Icon, label }) {
  return (
    <div
      className="flex items-center gap-2 px-3 py-2.5 bg-white/85 backdrop-blur border border-zinc-200 rounded-sm shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
    >
      <Icon size={16} strokeWidth={1.9} color="#FD7800" />
      <span className="text-[11px] font-bold text-zinc-800 leading-tight">
        {label}
      </span>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
    </svg>
  );
}
