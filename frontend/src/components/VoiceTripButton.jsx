import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { Mic, Loader2, Square } from "lucide-react";

/**
 * VoiceTripButton — hands-free Telugu/English trip dictation.
 * Uses the browser Web Speech API (SpeechRecognition) with lang="te-IN" (falls back to en-IN).
 * On stop, the transcript is sent to /api/ai/parse-trip which returns structured trip fields
 * that we pass to the parent via onParsed().
 */
export default function VoiceTripButton({ onParsed, className = "" }) {
  const [listening, setListening] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [interim, setInterim] = useState("");
  const recRef = useRef(null);
  const supported = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

  useEffect(() => () => {
    try { recRef.current?.stop(); } catch { /* ignore */ }
  }, []);

  const start = () => {
    if (!supported) {
      toast.error("Voice not supported in this browser — try Chrome");
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    rec.lang = "te-IN"; // Telugu-India; also accepts English keywords
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;
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
        const { data } = await api.post("/ai/parse-trip", { transcript: text });
        toast.success(`Voice parsed — ${Object.keys(data.parsed || {}).length} fields`);
        onParsed?.(data.parsed || {}, text);
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

  const stop = () => {
    try { recRef.current?.stop(); } catch { /* ignore */ }
  };

  if (parsing) {
    return (
      <button data-testid="voice-btn-parsing" disabled className={`inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-zinc-300 rounded-sm text-zinc-500 ${className}`}>
        <Loader2 size={14} className="animate-spin" /> Parsing…
      </button>
    );
  }
  if (listening) {
    return (
      <div className={`inline-flex items-center gap-2 ${className}`}>
        <button data-testid="voice-btn-stop" onClick={stop} className="inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-rose-500 bg-rose-50 text-rose-700 rounded-sm animate-pulse">
          <Square size={14} /> Stop
        </button>
        {interim && (
          <span className="text-xs text-zinc-500 truncate max-w-xs" data-testid="voice-interim">{interim}</span>
        )}
      </div>
    );
  }
  return (
    <button
      data-testid="voice-btn-start"
      onClick={start}
      className={`inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-emerald-300 text-emerald-800 bg-emerald-50 rounded-sm hover:bg-emerald-100 ${className}`}
      title="Dictate this trip"
    >
      <Mic size={14} /> Voice · వాయిస్
    </button>
  );
}
