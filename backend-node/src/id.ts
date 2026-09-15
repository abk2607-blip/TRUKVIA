import { randomUUID } from 'node:crypto';

/**
 * TRUKVIA · Phase-3 · Gate-4 — server-side ID generator.
 * Faithful shadow of `backend/models.py::new_id`:
 *   return f"{prefix}{uuid.uuid4().hex[:16]}"
 */
export function newId(prefix = ''): string {
  return prefix + randomUUID().replace(/-/g, '').slice(0, 16);
}
