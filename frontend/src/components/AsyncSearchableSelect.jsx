// Iter68 — Async variant of SearchableSelect.
// Query results are fetched from the server on every keystroke (debounced).
// The picker keeps the currently-selected option visible even when it isn't
// in the current search page — the parent passes `selectedOption` for that.
import React, { useEffect, useRef, useState } from "react";
import { Search, Plus, X, ChevronDown, Check, Loader2 } from "lucide-react";

/**
 * Props:
 *   value          : string  (currently selected id)
 *   selectedOption : { value, label, meta? } | null   — snapshot of the currently-
 *                    selected option, used so it stays visible in the button/list
 *                    even before/after searches without extra fetches.
 *   fetchOptions   : async (q) => [{value, label, meta}]
 *                    Called on debounced input change and when the dropdown opens.
 *   onChange       : (value, optionObj) => void
 *   onCreateNew    : () => void
 *   createLabel    : string
 *   placeholder    : string
 *   dataTestId     : string
 *   allowClear     : bool
 *   debounceMs     : number (default 300)
 */
export default function AsyncSearchableSelect({
  value = "",
  selectedOption = null,
  fetchOptions,
  onChange,
  onCreateNew,
  createLabel = "+ Add New",
  placeholder = "Search…",
  dataTestId = "async-select",
  allowClear = true,
  debounceMs = 300,
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const reqIdRef = useRef(0);

  // Close on outside click
  useEffect(() => {
    const onDoc = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
        setQ("");
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Focus input on open
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  // Debounced fetch on q change (or open)
  useEffect(() => {
    if (!open) return;
    const reqId = ++reqIdRef.current;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const res = await fetchOptions?.(q.trim());
        if (reqId === reqIdRef.current) {
          setOptions(Array.isArray(res) ? res : []);
        }
      } catch {
        if (reqId === reqIdRef.current) setOptions([]);
      } finally {
        if (reqId === reqIdRef.current) setLoading(false);
      }
    }, q ? debounceMs : 0);
    return () => clearTimeout(timer);
  }, [q, open, fetchOptions, debounceMs]);

  const pick = (opt) => {
    onChange?.(opt.value, opt);
    setOpen(false);
    setQ("");
  };

  const display = selectedOption?.label || "";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid={dataTestId}
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 border border-zinc-300 px-3 py-2 rounded-sm text-sm bg-white hover:border-zinc-950 focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
      >
        <span className={`truncate text-left flex-1 ${value ? "text-zinc-900" : "text-zinc-400"}`}>
          {value ? display || value : placeholder}
        </span>
        {value && allowClear && (
          <span
            role="button"
            data-testid={`${dataTestId}-clear`}
            onClick={(e) => {
              e.stopPropagation();
              onChange?.("", null);
            }}
            className="text-zinc-400 hover:text-rose-600"
          >
            <X size={14} />
          </span>
        )}
        <ChevronDown size={14} className="text-zinc-400 flex-shrink-0" />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-white border border-zinc-950 rounded-sm shadow-lg max-h-72 overflow-hidden flex flex-col">
          <div className="flex items-center gap-2 px-2 py-2 border-b border-zinc-200 bg-zinc-50">
            <Search size={14} className="text-zinc-400" />
            <input
              ref={inputRef}
              data-testid={`${dataTestId}-input`}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Type name, phone, GSTIN, or code…"
              className="flex-1 bg-transparent outline-none text-sm"
            />
            {loading && <Loader2 size={14} className="animate-spin text-zinc-400" />}
          </div>

          {onCreateNew && (
            <button
              type="button"
              data-testid={`${dataTestId}-create`}
              onClick={() => {
                onCreateNew();
                setOpen(false);
                setQ("");
              }}
              className="flex items-center gap-2 px-3 py-2 text-sm text-emerald-800 bg-emerald-50 hover:bg-emerald-100 border-b border-emerald-200 font-semibold"
            >
              <Plus size={14} />
              {createLabel}
              {q && <span className="ml-1 text-xs text-emerald-600">"{q}"</span>}
            </button>
          )}

          <div className="overflow-y-auto flex-1">
            {loading && options.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-zinc-400">Searching…</div>
            ) : options.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-zinc-400">
                {q ? "No matches" : "Type to search"}
              </div>
            ) : (
              options.map((o) => (
                <button
                  type="button"
                  key={o.value}
                  data-testid={`${dataTestId}-opt-${o.value}`}
                  onClick={() => pick(o)}
                  className={`w-full flex items-start gap-2 px-3 py-2 text-left text-sm hover:bg-zinc-100 border-b border-zinc-100 ${o.value === value ? "bg-zinc-50" : ""}`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="truncate">{o.label}</div>
                    {o.meta && <div className="text-[11px] text-zinc-500 truncate">{o.meta}</div>}
                  </div>
                  {o.value === value && <Check size={14} className="text-emerald-600 flex-shrink-0 mt-0.5" />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
