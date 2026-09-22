# Phase 6 — Slice 2c, unit 13: `replay_pending_failures`

Status: **GREEN**. Parity `checks 37 PASS 37 FAIL 0`.

The retry driver over the existing `fin_hook_failures` queue, ported to
`apps/api/src/fin/fin-hook.ts` as `replayPendingFailures`. **No new queue was
invented** — this reads and writes the same collection, with the same
documents, that Python has always used.

## What it does

Selects queued failures, reprojects each one, and records the outcome.

```
status ∈ {pending, retrying}
optional user_id / company_id scope
next_attempt_at <= now          unless ignore_schedule
sort by next_attempt_at
limit clamped to [1, 10000]     when Python-truthy
```

Success rewrites the row to `resolved` with `resolved_at` and
`last_attempt_at`. Failure increments `retry_count`, appends to `history`
(keeping the last four prior entries plus the new one), computes a fresh
backoff from the **new** count, and sets `permanently_failed` at
`retry_count >= MAX_RETRIES (8)` — otherwise `retrying`.

`remaining` in the report drops the schedule filter, so it counts what is
still outstanding rather than what is currently due.

## The choke point it uses

`replayPendingFailures` does **not** call the hook. It calls a private
`reprojectForReplay` that *throws*, mirroring `reproject_source` rather than
`hook_after_source_write` — because the hook swallows failures into the queue,
and a replay driver that queued its own retries would double-count every one
of them.

## How the parity harness produces failures honestly

Nothing is stubbed. Failures come from a `wallet_recharge` whose
`wallet_code` cannot be resolved, which raises inside `_persist_legs` exactly
as it would in production; successes come from one that resolves. Two helper
ops make the time-based behaviour testable without waiting:

- `age` rewinds `next_attempt_at` so a row becomes due now
- `setcount` forces a `retry_count` so the `MAX_RETRIES` boundary is reached
  in one step instead of eight

Both databases are driven through the **same ordered ten-step scenario** and
compared after every step — on both the return value and the entire queue.

The scenario covers: nothing due yet; `ignore_schedule` overriding that; a dry
run changing nothing; the fresh backoff after a real attempt; exactly one row
aged into being due; `limit` honoured in `next_attempt_at` order; a fixed
source resolving and keeping its id; the `MAX_RETRIES` boundary; a
`permanently_failed` row never being selected again; and a replay for another
tenant touching nothing.

## Assertions the step comparison cannot express

```
PASS  a source that projects cleanly never enters the queue
PASS  a row tips into permanently_failed at MAX_RETRIES, not before
PASS  every retrying row has a non-zero retry_count
PASS  ids survive every transition
PASS  history never grows past five entries
PASS  final status and retry_count agree for every queued source
```

## Verification

```
npx tsx scripts/fin-replay-parity.ts   # 37/37
```

## Not done here

- No queue schema changed; no row normalised.
- No admin endpoint exposed for it in this unit.
- The Python implementation remains in place as the rollback path.
