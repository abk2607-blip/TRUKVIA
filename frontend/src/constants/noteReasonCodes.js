// Iter132c C2 · CN/DN reason codes (frontend constants; no backend enum endpoint).
// Values are free strings; backend does not validate a fixed enum today.

export const CREDIT_REASONS = [
  { value: "quality_claim", label: "Quality claim" },
  { value: "rate_correction", label: "Rate correction" },
  { value: "short_delivery", label: "Short delivery / shortage" },
  { value: "discount", label: "Discount / rebate" },
  { value: "other", label: "Other" },
];

export const DEBIT_REASONS = [
  { value: "rate_correction", label: "Rate correction (upward)" },
  { value: "freight_escalation", label: "Freight escalation" },
  { value: "missed_halting", label: "Missed halting charge" },
  { value: "additional_charge", label: "Additional charge" },
  { value: "other", label: "Other" },
];

export function reasonsFor(kind) {
  return kind === "debit" ? DEBIT_REASONS : CREDIT_REASONS;
}
