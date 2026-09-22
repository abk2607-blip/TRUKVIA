/**
 * Python-compatible JSON rendering.
 *
 * FastAPI's JSONResponse emits `json.dumps(content, ensure_ascii=False,
 * allow_nan=False, separators=(",", ":"))`. Two differences from
 * JSON.stringify matter for parity, both found on real data (2026-09-21):
 *
 *   1. A float with no fractional part renders as `0.0` in Python and `0` in
 *      JavaScript. 20 of 66 migrated Fastify routes differ on exactly this.
 *      Postgres hands numeric columns back as strings, so the type is known
 *      here and can be rendered Python-style — the Mongo driver could not.
 *   2. Timestamps: Python returns the stored ISO string with a `+00:00`
 *      offset; Postgres formats `timestamptz` as `... +00`.
 *
 * `raw()` marks a pre-rendered numeric token so it survives serialization.
 */

const RAW = Symbol('py-raw-number');

export interface RawNumber {
  [RAW]: string;
}

export function raw(token: string): RawNumber {
  return { [RAW]: token } as RawNumber;
}

function isRaw(v: unknown): v is RawNumber {
  return typeof v === 'object' && v !== null && RAW in (v as Record<symbol, unknown>);
}

/**
 * Render a numeric column the way Python's repr(float) does:
 *   "0.00"      -> 0.0
 *   "29593.00"  -> 29593.0
 *   "24.539334" -> 24.539334
 * Returns null for null so the caller can emit JSON null.
 */
export function pyFloat(value: string | number | null): RawNumber | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return raw(Number.isInteger(n) ? `${n}.0` : String(n));
}

/**
 * Convert a Postgres timestamptz ("2026-08-05 08:40:35.451348+00") to the
 * datetime.isoformat() shape Python returns ("2026-08-05T08:40:35.451348+00:00").
 * Microseconds are padded to 6 digits when present and omitted when absent,
 * which is what isoformat() does.
 */
export function pyIsoTimestamp(value: string | null): string | null {
  if (!value) return null;
  const m = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(?:([+-]\d{2})(?::?(\d{2}))?|Z)?$/.exec(
    value,
  );
  if (!m) return value;
  const [, d, t, frac, offH, offM] = m;
  const fraction = frac ? `.${frac.padEnd(6, '0')}` : '';
  const offset = offH ? `${offH}:${offM ?? '00'}` : '+00:00';
  return `${d}T${t}${fraction}${offset}`;
}

/** json.dumps(..., ensure_ascii=False, separators=(",", ":")) */
export function pyDumps(value: unknown): string {
  if (isRaw(value)) return (value as unknown as Record<symbol, string>)[RAW] as string;
  if (value === null || value === undefined) return 'null';
  switch (typeof value) {
    case 'boolean':
      return value ? 'true' : 'false';
    case 'number':
      return Number.isInteger(value) ? String(value) : String(value);
    case 'string':
      return JSON.stringify(value);
    default:
      break;
  }
  if (Array.isArray(value)) return `[${value.map(pyDumps).join(',')}]`;
  if (value instanceof Date) return JSON.stringify(value.toISOString());
  const entries = Object.entries(value as Record<string, unknown>).filter(
    ([, v]) => v !== undefined,
  );
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${pyDumps(v)}`).join(',')}}`;
}
