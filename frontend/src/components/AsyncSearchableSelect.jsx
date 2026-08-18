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
  const [fetchError, setFetchError] = useState(false); // Iter87 — surface backend blip clearly
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

  // Debounced fetch on q change (or open) — Iter87: single silent retry on failure
  // so a transient backend hot-reload during typing doesn't produce a confusing
  // "Type to search" empty state.
  useEffect(() => {
    if (!open) return;
    const reqId = ++reqIdRef.current;
    setLoading(true);
    setFetchError(false);
    const timer = setTimeout(async () => {
      const attempt = async () => {
        return await fetchOptions?.(q.trim());
      };
      try {
        let res;
        try {
          res = await attempt();
        } catch (_) {
          // Silent retry once after 900ms — covers hot-reload / cold-start blips
          await new Promise((r) => setTimeout(r, 900));
          res = await attempt();
        }
        if (reqId === reqIdRef.current) {
          setOptions(Array.isArray(res) ? res : []);
        }
      } catch {
        if (reqId === reqIdRef.current) {
          setOptions([]);
          setFetchError(true);
        }
      } finally {
        if (reqId === reqIdRef.current) setLoading(false);
      }
    }, q ? debounceMs : 0);
    return () => clearTimeout(timer);
  }, [q, open, fetchOptions, debounceMs]);

  // Iter70 — Local cache of the last-picked option so the button shows the
  // label instantly (rather than the raw id) while the parent's async
  // `selectedOption` prop is still catching up. Cleared when value clears.
  const [lastPicked, setLastPicked] = useState(null);
  useEffect(() => {
    if (!value) setLastPicked(null);
  }, [value]);

  const pick = (opt) => {
    setLastPicked(opt);
    onChange?.(opt.value, opt);
    setOpen(false);
    setQ("");
  };

  const display =
    (selectedOption?.value === value && selectedOption?.label) ||
    (lastPicked?.value === value && lastPicked?.label) ||
    "";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid={dataTestId}
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 border border-zinc-300 px-3 py-2 rounded-sm text-sm bg-white hover:border-zinc-950 focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none"
      >
        <span className={`truncate text-left flex-1 ${value ? "text-zinc-900" : "text-zinc-400"}`}>
          {value ? (display || "…") : placeholder}
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
            ) : fetchError ? (
              <div className="px-3 py-6 text-center text-xs text-rose-700 bg-rose-50 border-b border-rose-200">
                Couldn't reach server. Retrying…
              </div>
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
