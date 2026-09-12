import React, { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";

/** Iter150H · CompanySourceBankSelector — company source-bank dropdown.
 * Default: primary active company-bank when available. Inactive accounts hidden.
 * Displays masked number only. Empty → legacy-compatible (no selection).
 * Props: value, onChange (id string), disabled.
 */
export default function CompanySourceBankSelector({ value, onChange, disabled }) {
  const { data = [] } = useQuery({
    queryKey: ["company-banks-selector"],
    queryFn: async () => (await api.get(`/company-bank-accounts`)).data,
  });
  const active = useMemo(() => (data || []).filter((r) => r.is_active), [data]);

  useEffect(() => {
    if (!value && active.length > 0) {
      const primary = active.find((r) => r.is_primary);
      if (primary) onChange?.(primary.id);
    }
  }, [active, value, onChange]);

  return (
    <select
      data-testid="company-source-bank-selector"
      disabled={disabled || active.length === 0}
      value={value || ""}
      onChange={(e) => onChange?.(e.target.value)}
      className="mt-1 w-full border border-zinc-300 px-2 py-1 rounded-sm text-sm disabled:bg-zinc-50 disabled:text-zinc-400"
    >
      <option value="" data-testid="company-source-bank-empty">
        {active.length === 0 ? "— No company bank account —" : "— Not selected —"}
      </option>
      {active.map((r) => (
        <option key={r.id} value={r.id} data-testid={`company-source-bank-option-${r.id}`}>
          {r.bank_name} · {r.masked_display || r.account_number}{r.is_primary ? " · Primary" : ""}
        </option>
      ))}
    </select>
  );
}
