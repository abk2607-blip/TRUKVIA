import React from "react";
import { useAuth } from "@/context/AuthContext";
import { Navigate } from "react-router-dom";
import { Truck, ShieldCheck, FileText, IndianRupee } from "lucide-react";

const HERO_IMG =
  "https://images.unsplash.com/photo-1591768793355-74d04bb6608f?crop=entropy&cs=srgb&fm=jpg&w=1600&q=85";

export default function Login() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen text-zinc-500">Loading...</div>
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
      {/* Left hero */}
      <div className="relative hidden md:block overflow-hidden grain">
        <img src={HERO_IMG} alt="Highway transport truck" className="absolute inset-0 w-full h-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-br from-black/70 via-black/40 to-black/60" />
        <div className="relative z-10 h-full flex flex-col justify-between p-10 text-white">
          <div>
            <div className="text-[11px] uppercase tracking-[0.3em] font-bold opacity-80">Bitumen Transport</div>
            <h1 className="mt-3 text-5xl font-black tracking-tighter leading-[0.95]">
              <span className="telugu">బిటుమెన్</span><br />ట్రాన్స్‌పోర్ట్<br />అకౌంటింగ్.
            </h1>
            <p className="mt-4 text-sm opacity-80 max-w-sm">
              GST invoicing, trip logs, expense tracking &amp; receivables — built for road transporters.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <Feature icon={Truck} te="ట్రిప్ లాగింగ్" en="Trip logging" />
            <Feature icon={FileText} te="GST ఇన్వాయిస్" en="GST invoices" />
            <Feature icon={IndianRupee} te="బాకీ ట్రాకింగ్" en="Receivables" />
            <Feature icon={ShieldCheck} te="సురక్షితం" en="Secure" />
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

          <button
            data-testid="google-login-button"
            onClick={handleLogin}
            className="mt-8 w-full inline-flex items-center justify-center gap-3 px-4 py-3 bg-zinc-950 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-zinc-950 hover:bg-white hover:text-zinc-950 transition-colors"
          >
            <GoogleIcon /> Continue with Google
          </button>

          <div className="relative my-4">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-zinc-200"></div></div>
            <div className="relative flex justify-center"><span className="bg-white px-2 text-[10px] uppercase tracking-widest text-zinc-500">or</span></div>
          </div>

          <button
            data-testid="demo-login-button"
            onClick={() => {
              localStorage.setItem("session_token", "test_session_bitumen_2026");
              window.location.href = "/dashboard";
            }}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-3 bg-amber-500 text-white text-sm font-semibold uppercase tracking-wider rounded-sm border border-amber-500 hover:bg-amber-600 transition-colors"
          >
            Continue as Demo — Skip Login
          </button>
          <p className="mt-1 text-[10px] text-zinc-400 text-center">Temporary — for testing the app without OAuth</p>

          <div className="mt-8 border-t border-zinc-200 pt-4">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold">Compliance</div>
            <div className="mt-1 text-xs text-zinc-600">GST 5% RCM · HSN 996791 · Andhra Pradesh format</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Feature({ icon: Icon, te, en }) {
  return (
    <div className="flex items-start gap-2 border border-white/20 p-3 rounded-sm bg-white/5">
      <Icon size={18} strokeWidth={1.5} />
      <div>
        <div className="telugu text-sm font-semibold">{te}</div>
        <div className="text-[10px] opacity-70">{en}</div>
      </div>
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
