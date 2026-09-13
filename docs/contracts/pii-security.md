# TRUKVIA · PII / Bank / Secrets Security Policy

**Contract tag:** `contract@v1.iter150j`
**Scope:** design policy for the current Python backend AND the future Node backend. This document does NOT authorise implementation. No encryption code is written on Python. No existing at-rest data is rewritten.

---

## 1 · Data Inventory

| Data class | Collection / field | Current at-rest state | Target policy | Reveal permission |
|---|---|---|---|---|
| Full bank account number (party) | `party_bank_accounts.account_number` | cleartext | Encrypt at rest on new-write path (Node) — envelope encryption (KMS-wrapped DEK per row). Legacy rows left untouched. | `view_bank_account_full` |
| Full bank account number (company) | `company_bank_accounts.account_number` | cleartext | Same | `view_bank_account_full` |
| Bank snapshot on payment | `*_payment.bank_snapshot`, `source_bank_snapshot` | masked-only (`masked_number`, `bank_name`, `ifsc`) | UNCHANGED. Already safe. | Not applicable — safe by construction |
| GSTIN | `parties.gstin`, `customers.gstin`, `suppliers.gstin`, `companies.gstin` | cleartext | No encryption; treat as business-sensitive. Mask in logs. | Any authenticated role |
| Driver DL number | `drivers.dl_number` | cleartext | Encrypt at rest on new-write (Node). Legacy untouched. | New permission `view_driver_kyc` (owner default) |
| Driver PAN | `drivers.pan_number` | cleartext | Same | `view_driver_kyc` |
| User email | `users.email` | cleartext | No encryption (used as login lookup). Mask in logs. | Owner + self |
| User phone | `users.phone` (if present) | cleartext | Encrypt at rest on new-write. Show last-4 by default. | Owner + self |
| Session token | `user_sessions.session_token` | opaque UUID | UNCHANGED. Rotate every 30 days. Add inactivity timeout on Node. | Never revealed |
| Provider API keys (Emergent LLM, Emergent Email) | `.env` | env-var (single-tenant) | Move to secrets manager (per-env) once independent deploy starts. NEVER in Mongo. NEVER in git. | Never revealed to app users |
| Per-tenant integration credentials (future Cashfree/Razorpay/VAHAN) | Not yet | — | Store in secrets manager, referenced by tenant integration config. NEVER in Mongo cleartext. | Never revealed to app users |
| Webhook signing secrets | Not yet | — | Same as above. | Never revealed |
| Audit log records | `audit_logs`, `approval_audits`, `policy_change_events` | append-only | UNCHANGED. Immutable. | Owner / accountant read-only |

## 2 · Masking Rules

| Field | Masking format |
|---|---|
| Account number (14–18 digits) | `XXXXXXXXXXXX7890` — last 4 exposed |
| DL number | `XX00YYY0000ZZZZ` → `XX00YYY0000****` — last 4 masked |
| PAN | `ABCDE1234F` → `ABCDE****F` — mid 4 masked |
| Phone | `+91-XXXXX-XX890` — last 3 exposed |
| Email | `j****@example.com` — first char + domain |
| GSTIN | shown in full to authenticated users; hashed in log fields |

Masking is applied at **serialisation time** for API responses (no cleartext ever leaves the boundary unless permission gate passes) AND at **log-write time** (Pino redaction filter on Node; explicit `logger.info(...)` sanitisation on Python).

## 3 · Encryption Targets (Node writer path only)

**Design.** Envelope encryption using a per-environment KEK (Key Encryption Key) managed by the deployment's secrets manager. Each encrypted row carries a random DEK (Data Encryption Key), wrapped by the KEK. Ciphertext + wrapped-DEK + IV stored in a JSON sub-document alongside the (now-empty) cleartext field for backward read compatibility.

**Row shape after encryption:**
```
{
  "account_number": "",                  // left empty on encrypted rows
  "bank_number_enc_v1": {
    "ct": "<base64 ciphertext>",
    "iv": "<base64 12-byte>",
    "dek_wrapped": "<base64 wrapped DEK>",
    "kek_id": "trukvia-prod-2026-01",
    "algo": "aes-256-gcm"
  }
}
```

**Version marker.** Field name (`bank_number_enc_v1`, `dl_enc_v1`, `pan_enc_v1`, `phone_enc_v1`) encodes the schema version. New versions can coexist during rotation.

**Read path priority.** If versioned field present → decrypt via `SecretsPort.decrypt`. Else fall back to legacy cleartext. Both paths apply masking at API-response boundary.

## 4 · Legacy vs New-write Policy

- **Legacy rows are NOT rewritten** during the Python→Node migration. Bulk decrypt-and-re-encrypt is destructive and out of scope.
- Any UPDATE that touches a legacy row on the Node path SHOULD upgrade it to the encrypted form. This is opportunistic backfill, not scheduled.
- A dedicated post-migration maintenance window MAY perform a full backfill under separate authorisation. Not part of Phase 1–12.

## 5 · Secrets Management

**Targets (in order of preference):**

1. AWS Secrets Manager or GCP Secret Manager once independent deploy starts.
2. Emergent-managed key vault for the interim.
3. `.env` for local dev only. NEVER committed. NEVER in prod containers.

**Rules:**

- Every secret has an owner, rotation cadence, and rotation runbook.
- Adapters (Cashfree, Razorpay, etc.) read secrets ONLY through the `SecretsPort` abstraction, never `process.env` directly.
- Log redaction filters strip any value that starts with a known secret prefix.
- Git pre-commit hook rejects any diff line containing a probable API-key regex.

## 6 · Reveal Audit

Every reveal of masked → full data writes to `audit_logs`:

```
{
  "action": "reveal_bank" | "reveal_kyc" | "reveal_email" | "reveal_phone",
  "actor_user_id": "...",
  "target_collection": "party_bank_accounts",
  "target_id": "...",
  "at": "ISO-8601 UTC",
  "ip": "<client ip>",
  "reason": "<optional user-supplied>"
}
```

Reveal endpoints:
- `GET /api/party-bank-accounts/{id}/reveal` — permission `view_bank_account_full`
- `GET /api/company-bank-accounts/{id}/reveal` — permission `view_bank_account_full`
- (Post-migration) `GET /api/drivers/{id}/kyc/reveal` — permission `view_driver_kyc`

Reveal audit rows are Class-A append-only.

## 7 · Class-A Failure Modes

- Full bank account number appearing in any log line.
- Full account number in any Approval / ApprovalRevision / ApprovalAudit payload.
- DL / PAN in any log line.
- Provider API key in git history.
- Provider API key returned to any frontend endpoint.
- Cross-tenant data leak via un-scoped mongo query.
- Reveal endpoint bypassing permission check.

Any Class-A hit blocks deploy and requires an incident postmortem.

## 8 · Deferred Decisions

- **KEK provider choice** — AWS KMS vs GCP KMS vs hosted HSM. Decision at Phase 10 depending on target deploy environment.
- **Field-level encryption library** — Node ships `crypto` (AES-256-GCM native); no external lib required. Confirmed acceptable.
- **PDF generator retention** — Consider keeping Python's ReportLab-based renderer behind a `ReportsPort` even after the general migration completes, to preserve pixel-parity on tax outputs. Decide at Phase 9.
- **Full backfill of legacy cleartext bank/PAN/DL rows** — scheduled maintenance window post-Phase-12. Not authorised now.

## 9 · What This Document Does NOT Do

- Does NOT authorise any encryption implementation.
- Does NOT authorise rewrite of existing at-rest data.
- Does NOT authorise a new reveal endpoint.
- Does NOT authorise switching secrets managers.
- Does NOT change any current permission or role.

All items in this document are conceptual policy for the future Node writer path. Any implementation requires separate authorisation.
