import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { Mic, Loader2, Square } from "lucide-react";

/**
 * VoiceButton — generic Telugu/English voice input.
 * Sends the transcript to /api/ai/parse with the given `context`.
 * Emits parsed fields via onParsed({...}, transcript).
 *
 * Props:
 *   context: 'trip' | 'invoice' | 'payment' | 'expense'
 *   onParsed(parsed, transcript): void
 *   label: string (button label)
 *   size: 'sm' | 'md'
 *   className
 */
export default function VoiceButton({
  context = "trip",
  onParsed,
  label = null,
  size = "md",
  className = "",
}) {
  const [listening, setListening] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [interim, setInterim] = useState("");
  const recRef = useRef(null);
  const supported = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

  useEffect(() => () => { try { recRef.current?.stop(); } catch { /* ignore */ } }, []);

  const start = () => {
    if (!supported) { toast.error("Voice not supported — try Chrome"); return; }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    rec.lang = "te-IN";
    rec.interimResults = true;
    rec.continuous = true;
    let finalText = "";
    rec.onresult = (ev) => {
      let live = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) finalText += r[0].transcript + " ";
        else live += r[0].transcript;
      }
      setInterim((finalText + live).trim());
    };
    rec.onend = async () => {
      setListening(false);
      const text = (finalText || interim).trim();
      setInterim("");
      if (!text) { toast.info("No voice detected"); return; }
      setParsing(true);
      try {
        const endpoint =
          context === "trip" ? "/ai/parse-trip"
          : context === "template" ? "/ai/parse-template"
          : "/ai/parse";
        const body = (context === "trip" || context === "template")
          ? { transcript: text }
          : { transcript: text, context };
        const { data } = await api.post(endpoint, body);
        const parsed = data.parsed || {};
        const count = Object.keys(parsed).filter((k) => parsed[k] !== "" && parsed[k] !== 0 && parsed[k] != null).length;
        toast.success(`Voice parsed — ${count} field(s)`);
        onParsed?.(parsed, text);
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Voice parse failed");
      } finally {
        setParsing(false);
      }
    };
    rec.onerror = (e) => {
      setListening(false);
      if (e.error !== "aborted") toast.error(`Voice error: ${e.error}`);
    };
    recRef.current = rec;
    try {
      rec.start();
      setListening(true);
      toast.info("Speak now… (Telugu / English)");
    } catch (e) {
      toast.error(`Cannot start mic: ${e.message}`);
    }
  };

  const stop = () => { try { recRef.current?.stop(); } catch { /* ignore */ } };

  const btnSize = size === "sm" ? "px-2 py-1 text-[10px]" : "px-3 py-2 text-xs";
  const tid = `voice-btn-${context}`;

  if (parsing) {
    return (
      <button data-testid={`${tid}-parsing`} disabled className={`inline-flex items-center gap-1 ${btnSize} uppercase tracking-wider border border-zinc-300 rounded-sm text-zinc-500 ${className}`}>
        <Loader2 size={12} className="animate-spin" /> Parsing…
      </button>
    );
  }
  if (listening) {
    return (
      <div className={`inline-flex items-center gap-2 ${className}`}>
        <button data-testid={`${tid}-stop`} onClick={stop} className={`inline-flex items-center gap-1 ${btnSize} uppercase tracking-wider border border-rose-500 bg-rose-50 text-rose-700 rounded-sm animate-pulse`}>
          <Square size={12} /> Stop
        </button>
        {interim && <span className="text-xs text-zinc-500 truncate max-w-[200px]" data-testid={`${tid}-interim`}>{interim}</span>}
      </div>
    );
  }
  return (
    <button
      data-testid={`${tid}-start`}
      onClick={start}
      title={`Dictate this ${context}`}
      className={`inline-flex items-center gap-1 ${btnSize} uppercase tracking-wider border border-emerald-300 text-emerald-800 bg-emerald-50 rounded-sm hover:bg-emerald-100 ${className}`}
    >
      <Mic size={12} /> {label ?? `Voice · వాయిస్`}
    </button>
  );
}
