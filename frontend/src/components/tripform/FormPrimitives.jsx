// Iter55 — Extracted from TripForm.jsx. Pure presentational primitives.
import React from "react";

export function Section({ title, children }) {
  return (
    <section className="border border-zinc-200 bg-white rounded-sm">
      <div className="px-5 py-3 border-b border-zinc-200 text-sm font-bold uppercase tracking-wider">
        {title}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Field({ label, required, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
        {label}{required && " *"}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
