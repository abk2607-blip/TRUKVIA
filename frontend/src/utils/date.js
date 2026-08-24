// Iter117 · Indian date-display format helpers.
// Presentation only — never touches storage. Mirrors the backend PDF
// helper `_fmt_ind_date` so Trip / Customer / Invoice / LR displays and
// generated PDFs render the same way (e.g. "23-Aug-2026").
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

/**
 * Format a date value in the Indian display convention `23-Aug-2026`.
 * Accepts a Date, ISO string, or "YYYY-MM-DD" string. Returns "—" for
 * empty / invalid input so UI cells stay aligned.
 */
export function formatIndDate(v) {
  if (!v && v !== 0) return "—";
  try {
    let d;
    if (v instanceof Date) {
      d = v;
    } else {
      const s = String(v);
      // "YYYY-MM-DD" or ISO datetime "YYYY-MM-DDTHH:MM..." — parse the date part
      // manually so we render the CALENDAR date the user entered (no TZ shift).
      const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
      if (m) {
        d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
      } else {
        d = new Date(s);
      }
    }
    if (isNaN(d.getTime())) return String(v);
    const dd = String(d.getDate()).padStart(2, "0");
    return `${dd}-${MONTHS[d.getMonth()]}-${d.getFullYear()}`;
  } catch {
    return String(v);
  }
}

/** Format a datetime value as `23-Aug-2026 · 14:35`. */
export function formatIndDateTime(v) {
  if (!v) return "—";
  try {
    const d = v instanceof Date ? v : new Date(v);
    if (isNaN(d.getTime())) return String(v);
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${dd}-${MONTHS[d.getMonth()]}-${d.getFullYear()} · ${hh}:${mm}`;
  } catch {
    return String(v);
  }
}
