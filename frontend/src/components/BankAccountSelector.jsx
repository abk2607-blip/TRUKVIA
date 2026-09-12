import React, { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";

/** BankAccountSelector — party bank account dropdown.
 * Default: primary active account when available. Inactive accounts hidden.
 * Displays masked number only. Empty → legacy-compatible (no selection).
 * Props: partyType, partyId, value, onChange (id string).
 */
export default function BankAccountSelector({ partyType, partyId, value, onChange, disabled }) {
  const { data = [] } = useQuery({
    queryKey: ["party-banks-selector", partyType, partyId],
    queryFn: async () => (await api.get(`/party-bank-accounts?party_type=${partyType}&party_id=${partyId}`)).data,
    enabled: Boolean(partyType && partyId),
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
      data-testid="bank-account-selector"
      disabled={disabled || active.length === 0}
      value={value || ""}
      onChange={(e) => onChange?.(e.target.value)}
      className="mt-1 w-full border border-zinc-300 px-2 py-1 rounded-sm text-sm disabled:bg-zinc-50 disabled:text-zinc-400"
    >
      <option value="" data-testid="bank-selector-empty">— No bank account —</option>
      {active.map((r) => (
        <option key={r.id} value={r.id} data-testid={`bank-selector-option-${r.id}`}>
          {r.bank_name} · {r.masked_display || r.account_number}{r.is_primary ? " · Primary" : ""}
        </option>
      ))}
    </select>
  );
}
