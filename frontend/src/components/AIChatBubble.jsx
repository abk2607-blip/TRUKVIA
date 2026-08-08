import { useEffect, useRef, useState } from "react";
import { MessageSquare, X, Send, Trash2, Plus, FileText, Loader2 } from "lucide-react";
import { getActiveCompanyId, API } from "@/api";
import { useAuth } from "@/context/AuthContext";

const SESSION_KEY = "ai_chat_session_id";
const OPEN_KEY = "ai_chat_open";

export default function AIChatBubble() {
  const { user, session } = useAuth();
  const [open, setOpen] = useState(() => sessionStorage.getItem(OPEN_KEY) === "1");
  const [sessionId, setSessionId] = useState(() => sessionStorage.getItem(SESSION_KEY) || "");
  const [messages, setMessages] = useState([]);   // {role, content, streaming?}
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => { sessionStorage.setItem(OPEN_KEY, open ? "1" : "0"); }, [open]);
  useEffect(() => {
    if (sessionId) sessionStorage.setItem(SESSION_KEY, sessionId);
    else sessionStorage.removeItem(SESSION_KEY);
  }, [sessionId]);

  // Load existing conversation when session available
  useEffect(() => {
    if (!sessionId || !open) return;
    const token = session?.session_token || localStorage.getItem("session_token");
    fetch(`${API}/ai/sessions/${sessionId}/messages`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.ok ? r.json() : []).then(msgs => setMessages(msgs.map(m => ({ role: m.role, content: m.content }))));
  }, [sessionId, open, session]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  if (!user) return null;

  const startNewChat = () => { setSessionId(""); setMessages([]); };

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setMessages(m => [...m, { role: "user", content: text }, { role: "assistant", content: "", streaming: true }]);
    setSending(true);
    try {
      const token = session?.session_token || localStorage.getItem("session_token");
      const cid = getActiveCompanyId() || "";
      const resp = await fetch(`${API}/ai/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...(cid ? { "X-Company-Id": cid } : {}),
        },
        body: JSON.stringify({ message: text, session_id: sessionId || null }),
      });
      if (!resp.ok) {
        const t = await resp.text();
        setMessages(m => {
          const copy = [...m];
          copy[copy.length - 1] = { role: "assistant", content: `Error: ${t.slice(0, 200)}` };
          return copy;
        });
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assembled = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 2);
          if (!raw.startsWith("data:")) continue;
          const json = raw.slice(5).trim();
          try {
            const ev = JSON.parse(json);
            if (ev.type === "text") {
              assembled += ev.delta || "";
              setMessages(m => {
                const copy = [...m];
                copy[copy.length - 1] = { role: "assistant", content: assembled, streaming: true };
                return copy;
              });
            } else if (ev.type === "done") {
              if (ev.session_id && !sessionId) setSessionId(ev.session_id);
              setMessages(m => {
                const copy = [...m];
                copy[copy.length - 1] = { role: "assistant", content: assembled };
                return copy;
              });
            } else if (ev.type === "error") {
              setMessages(m => {
                const copy = [...m];
                copy[copy.length - 1] = { role: "assistant", content: `Error: ${ev.message}` };
                return copy;
              });
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      setMessages(m => {
        const copy = [...m];
        copy[copy.length - 1] = { role: "assistant", content: `Network error: ${e.message}` };
        return copy;
      });
    } finally { setSending(false); }
  };

  const quickPrompts = [
    "What is this month's net profit?",
    "Show overdue invoices",
    "Top 5 profitable vehicles",
    "Which customers have pending payments?",
    "Show recent trips",
  ];

  const generateReport = async () => {
    const q = input.trim();
    if (!q || reportLoading) return;
    setReportLoading(true);
    try {
      const token = session?.session_token || localStorage.getItem("session_token");
      const cid = getActiveCompanyId() || "";
      const resp = await fetch(`${API}/ai/report`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...(cid ? { "X-Company-Id": cid } : {}),
        },
        body: JSON.stringify({ query: q }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setMessages(m => [...m,
        { role: "user", content: q },
        { role: "assistant", content: `📊 Report generated for: "${q}". Opened in a new tab.` }
      ]);
      setInput("");
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", content: `Report failed: ${e.message || e}` }]);
    } finally {
      setReportLoading(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        data-testid="ai-chat-open"
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full bg-gradient-to-r from-amber-500 to-orange-600 text-white px-5 py-3 shadow-lg hover:scale-105 transition"
      >
        <MessageSquare size={20} />
        <span className="font-semibold text-sm">Ask AI</span>
      </button>
    );
  }

  return (
    <div
      data-testid="ai-chat-panel"
      className="fixed bottom-6 right-6 z-50 w-[92vw] max-w-md h-[80vh] max-h-[640px] flex flex-col bg-white rounded-2xl shadow-2xl border border-zinc-200 overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-gradient-to-r from-amber-500 to-orange-600 text-white">
        <div className="flex items-center gap-2">
          <MessageSquare size={18} />
          <div>
            <div className="text-sm font-bold">Business AI Assistant</div>
            <div className="text-[10px] opacity-80">Gemini · Active company only</div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={startNewChat} title="New chat" data-testid="ai-chat-new" className="p-1.5 rounded hover:bg-white/20"><Plus size={16} /></button>
          <button onClick={() => setOpen(false)} title="Close" data-testid="ai-chat-close" className="p-1.5 rounded hover:bg-white/20"><X size={16} /></button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3 bg-zinc-50" data-testid="ai-chat-messages">
        {messages.length === 0 && (
          <div className="space-y-3">
            <div className="text-sm text-zinc-600">
              Ask me anything about your <b>{ /* active company shown implicitly */ }</b> business data.
            </div>
            <div className="flex flex-wrap gap-2">
              {quickPrompts.map(p => (
                <button key={p} onClick={() => setInput(p)} className="text-xs px-3 py-1.5 bg-white border rounded-full hover:bg-amber-50">
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`${m.role === "user" ? "bg-amber-500 text-white" : "bg-white border"} rounded-2xl px-3 py-2 text-sm max-w-[85%] whitespace-pre-wrap break-words leading-relaxed`}>
              {m.content || (m.streaming ? "…" : "")}
            </div>
          </div>
        ))}
        {sending && messages[messages.length - 1]?.streaming && (
          <div className="flex gap-1 text-zinc-400 text-xs pl-2">
            <span className="animate-pulse">●</span>
            <span className="animate-pulse delay-100">●</span>
            <span className="animate-pulse delay-200">●</span>
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="p-3 border-t bg-white">
        <div className="flex gap-2 items-end">
          <textarea
            rows={1}
            data-testid="ai-chat-input"
            className="flex-1 resize-none border border-zinc-300 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 rounded-lg px-3 py-2 text-sm outline-none max-h-24"
            placeholder="Ask a question — e.g. 'Show overdue invoices' or 'Last month diesel by vehicle'"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
          />
          <button
            data-testid="ai-chat-report"
            onClick={generateReport}
            disabled={reportLoading || !input.trim()}
            title="Generate PDF report from this query"
            className="rounded-full p-2.5 bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-40"
          >
            {reportLoading ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
          </button>
          <button
            data-testid="ai-chat-send"
            onClick={send}
            disabled={sending || !input.trim()}
            className="rounded-full p-2.5 bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-40"
          >
            <Send size={16} />
          </button>
        </div>
        <div className="text-[10px] text-zinc-400 mt-1.5 px-1">Chat 💬 · Report 📄 (green button generates a PDF)</div>
      </div>
    </div>
  );
}
