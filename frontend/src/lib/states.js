// Complete list of Indian States and Union Territories with GST State Codes.
// Use this everywhere a state dropdown is needed (Customers, Suppliers,
// Company/Consignor/Consignee, Vehicle owner, etc.) to keep master data clean.
export const INDIA_STATES = [
  { name: "Andhra Pradesh", code: "37", ut: false },
  { name: "Arunachal Pradesh", code: "12", ut: false },
  { name: "Assam", code: "18", ut: false },
  { name: "Bihar", code: "10", ut: false },
  { name: "Chhattisgarh", code: "22", ut: false },
  { name: "Goa", code: "30", ut: false },
  { name: "Gujarat", code: "24", ut: false },
  { name: "Haryana", code: "06", ut: false },
  { name: "Himachal Pradesh", code: "02", ut: false },
  { name: "Jharkhand", code: "20", ut: false },
  { name: "Karnataka", code: "29", ut: false },
  { name: "Kerala", code: "32", ut: false },
  { name: "Madhya Pradesh", code: "23", ut: false },
  { name: "Maharashtra", code: "27", ut: false },
  { name: "Manipur", code: "14", ut: false },
  { name: "Meghalaya", code: "17", ut: false },
  { name: "Mizoram", code: "15", ut: false },
  { name: "Nagaland", code: "13", ut: false },
  { name: "Odisha", code: "21", ut: false },
  { name: "Punjab", code: "03", ut: false },
  { name: "Rajasthan", code: "08", ut: false },
  { name: "Sikkim", code: "11", ut: false },
  { name: "Tamil Nadu", code: "33", ut: false },
  { name: "Telangana", code: "36", ut: false },
  { name: "Tripura", code: "16", ut: false },
  { name: "Uttar Pradesh", code: "09", ut: false },
  { name: "Uttarakhand", code: "05", ut: false },
  { name: "West Bengal", code: "19", ut: false },
  // Union Territories
  { name: "Andaman and Nicobar Islands", code: "35", ut: true },
  { name: "Chandigarh", code: "04", ut: true },
  { name: "Dadra and Nagar Haveli and Daman and Diu", code: "26", ut: true },
  { name: "Delhi", code: "07", ut: true },
  { name: "Jammu and Kashmir", code: "01", ut: true },
  { name: "Ladakh", code: "38", ut: true },
  { name: "Lakshadweep", code: "31", ut: true },
  { name: "Puducherry", code: "34", ut: true },
];

export function stateCode(name) {
  if (!name) return "";
  const s = String(name).trim().toLowerCase();
  const m = INDIA_STATES.find((x) => x.name.toLowerCase() === s);
  return m?.code || "";
}

// Reusable dropdown component
import React from "react";
export function StateSelect({ value, onChange, className, dataTestId, includeEmpty = true, placeholder = "Select State" }) {
  return (
    <select
      data-testid={dataTestId}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
      className={className}
    >
      {includeEmpty && <option value="">{placeholder}</option>}
      <optgroup label="States">
        {INDIA_STATES.filter((s) => !s.ut).map((s) => (
          <option key={s.code} value={s.name}>{s.name}</option>
        ))}
      </optgroup>
      <optgroup label="Union Territories">
        {INDIA_STATES.filter((s) => s.ut).map((s) => (
          <option key={s.code} value={s.name}>{s.name}</option>
        ))}
      </optgroup>
    </select>
  );
}
