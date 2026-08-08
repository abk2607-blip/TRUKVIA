import React, { useState, useRef, useEffect } from "react";
import { Search, Plus, X, ChevronDown, Check } from "lucide-react";

/**
 * SearchableSelect — type-to-filter dropdown with optional inline "Create New" button.
 *
 * Props:
 *   options: [{ value, label, meta? }]  — meta is a small secondary line (phone, GSTIN...)
 *   value: string (current selected value)
 *   onChange: (value, optionObj) => void
 *   onCreateNew: () => void  — when provided, shows a "+ Add New" row at top
 *   placeholder: string
 *   dataTestId: string
 *   disabled: bool
 *   allowClear: bool  — show × to clear
 *   className: string
 */
export default function SearchableSelect({
  options = [],
  value = "",
  onChange,
  onCreateNew,
  createLabel = "+ Add New",
  placeholder = "Search or select…",
  dataTestId = "searchable-select",
  disabled = false,
  allowClear = true,
  className = "",
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const rootRef = useRef(null);
  const inputRef = useRef(null);

  const selected = options.find((o) => o.value === value) || null;

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

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const qLower = q.trim().toLowerCase();
  const filtered = qLower
    ? options.filter((o) =>
        (o.label || "").toLowerCase().includes(qLower) ||
        (o.meta || "").toLowerCase().includes(qLower)
      )
    : options;

  const pick = (opt) => {
    onChange?.(opt.value, opt);
    setOpen(false);
    setQ("");
  };

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        type="button"
        data-testid={dataTestId}
        disabled={disabled}
        onClick={() => !disabled && setOpen((o) => !o)}
        className={`w-full flex items-center justify-between gap-2 border border-zinc-300 px-3 py-2 rounded-sm text-sm bg-white hover:border-zinc-950 focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950 outline-none ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
      >
        <span className={`truncate text-left flex-1 ${selected ? "text-zinc-900" : "text-zinc-400"}`}>
          {selected ? selected.label : placeholder}
        </span>
        {selected && allowClear && !disabled && (
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
              placeholder="Type to search…"
              className="flex-1 bg-transparent outline-none text-sm"
            />
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
            {filtered.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-zinc-400">
                {options.length === 0 ? "No records yet" : "No matches"}
              </div>
            ) : (
              filtered.map((o) => (
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
