/**
 * CPython 3.11's C `date.fromisoformat`, returning the proleptic Gregorian
 * ordinal so that a difference of two results is exactly Python's
 * `(a - b).days`.
 *
 * This is a port of the gate-locked implementation in
 * backend-node/src/routes/fin-day-closure-late-entries.ts (Gate 7r, 542/542
 * byte-exact against the live server), kept identical rather than rewritten.
 *
 * Why not a regex: 3.11 accepts more than YYYY-MM-DD. It also takes the basic
 * form `20260903`, ISO week dates `2026-W36` and `2026-W36-4`, and it applies
 * real calendar validation. A handler that guards with
 * `/^\d{4}-\d{2}-\d{2}$/` rejects inputs Python accepts, and every such input
 * is a 400 here against a 200 there.
 */
const DAYS_BEFORE_MONTH = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
const DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

const isLeap = (y: number): boolean => y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);

const daysInMonth = (y: number, m: number): number =>
  m === 2 && isLeap(y) ? 29 : (DAYS_IN_MONTH[m] as number);

function ymdToOrd(y: number, m: number, d: number): number {
  const x = y - 1;
  return (
    x * 365 +
    Math.trunc(x / 4) -
    Math.trunc(x / 100) +
    Math.trunc(x / 400) +
    (DAYS_BEFORE_MONTH[m] as number) +
    (m > 2 && isLeap(y) ? 1 : 0) +
    d
  );
}

function ordToYear(ord: number): number {
  let n = ord - 1;
  const n400 = Math.floor(n / 146097);
  n -= n400 * 146097;
  const n100 = Math.floor(n / 36524);
  n -= n100 * 36524;
  const n4 = Math.floor(n / 1461);
  n -= n4 * 1461;
  const n1 = Math.floor(n / 365);
  const year = n400 * 400 + n100 * 100 + n4 * 4 + n1 + 1;
  return n1 === 4 || n100 === 4 ? year - 1 : year;
}

/** The ordinal, or null when CPython would raise ValueError. */
export function pyIsoDateOrdinal(s: string): number | null {
  const b = Buffer.from(s, 'utf8');
  const len = b.length;
  if (len !== 7 && len !== 8 && len !== 10) return null;
  const at = (i: number): number => (i < len ? (b[i] as number) : 0);
  let p = 0;
  const digits = (n: number): number | null => {
    let v = 0;
    for (let k = 0; k < n; k += 1) {
      const t = at(p) - 0x30;
      p += 1;
      if (t < 0 || t > 9) return null;
      v = v * 10 + t;
    }
    return v;
  };

  const year = digits(4);
  if (year === null) return null;
  const sep = at(p) === 0x2d; // '-'
  if (sep) p += 1;

  if (at(p) === 0x57) {
    // 'W' — ISO week date
    p += 1;
    const week = digits(2);
    if (week === null) return null;
    let day = 1;
    if (p < len) {
      if (sep) {
        const dash = at(p);
        p += 1;
        if (dash !== 0x2d) return null;
      }
      const d = digits(1);
      if (d === null) return null;
      day = d;
    }
    if (year < 1) return null;
    const jan1 = ymdToOrd(year, 1, 1);
    const firstWeekday = (jan1 + 6) % 7;
    if (week <= 0 || week >= 53) {
      const has53 = week === 53 && (firstWeekday === 3 || (firstWeekday === 2 && isLeap(year)));
      if (!has53) return null;
    }
    if (day <= 0 || day >= 8) return null;
    const ord = jan1 - firstWeekday + (firstWeekday > 3 ? 7 : 0) + (week - 1) * 7 + day - 1;
    const y = ordToYear(ord);
    return y >= 1 && y <= 9999 ? ord : null;
  }

  const month = digits(2);
  if (month === null) return null;
  if (sep) {
    const dash = at(p);
    p += 1;
    if (dash !== 0x2d) return null;
  }
  const day = digits(2);
  if (day === null) return null;
  if (year < 1 || year > 9999 || month < 1 || month > 12) return null;
  if (day < 1 || day > daysInMonth(year, month)) return null;
  return ymdToOrd(year, month, day);
}

/** `date.fromisoformat` acceptance only. */
export const pyIsoDateValid = (s: string): boolean => pyIsoDateOrdinal(s) !== null;
