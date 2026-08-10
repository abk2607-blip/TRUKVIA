# Deployment Guide — Regression Guard Enforcement

**Purpose:** Prevent any build with failing critical regression tests from
reaching production. This document lists **three independent enforcement
layers** that together guarantee bad code cannot be deployed.

If even one layer is active, deploys will be blocked on regression failures.
For maximum safety, enable **all three**.

---

## Layer 1 (Required) — GitHub Actions Required Status Check

The workflow at `.github/workflows/regression-guard.yml` runs the full
iter42-51 regression suite (73 tests) plus a live Trip-Edit smoke test on
every push and pull-request.

### Enable as a Required Status Check on `main`

1. **Push the workflow to GitHub** (already in `.github/workflows/`).
2. In GitHub, open **Settings → Branches → Branch protection rules**.
3. Add a rule for `main` (or `master` / `production`).
4. Tick **Require status checks to pass before merging**.
5. Search for `Iter42-50 Regression Suite` and tick it.
6. (Recommended) Tick **Require branches to be up to date before merging**.
7. Save.

From this point on, GitHub blocks any merge to `main` that has a failing
regression check. That in turn blocks the deploy pipeline that promotes
`main` builds to production.

### Verify

```bash
# Trigger the workflow manually
gh workflow run regression-guard.yml --ref main

# Watch the run
gh run watch
```

Expected outcome: a green tick appears next to the commit on GitHub; a red
X blocks the PR from merging.

---

## Layer 2 (Recommended) — Runtime Strict Mode

Even if a developer bypasses GitHub (e.g. pushes with `--no-verify` or force-
pushes a broken commit), the backend itself can refuse to serve production
traffic when the regression guard reports a failure.

### Enable

Set the following env var on your **production** deployment ONLY (never in
dev / staging preview):

```bash
REGRESSION_GUARD_STRICT=1
```

### How it works

- Backend runs `scripts/run_regression.sh` in a background task every hour
  (first check ~30s after boot).
- The result is written to `db.deploy_status`.
- With `REGRESSION_GUARD_STRICT=1`, the public `GET /api/auth/health`
  endpoint returns HTTP **503** whenever the latest guard result is `fail`.
- Emergent's platform (and every load balancer / K8s liveness probe / ELB
  target group in the industry) treats 503 as an unhealthy instance and
  refuses to send traffic to it — and refuses to promote a new build whose
  pods report 503 in the readiness phase.

### Verify

```bash
# Local test — kill a critical test, restart backend, then hit /auth/health
export REGRESSION_GUARD_STRICT=1
sudo supervisorctl restart backend
sleep 60   # wait for the first guard cycle
curl -s -o /dev/null -w "%{http_code}\n" $REACT_APP_BACKEND_URL/api/auth/health
# Expected: 503 if any critical test is broken; 200 if green
```

### Rollback

Unset `REGRESSION_GUARD_STRICT` (or set it to `0`) and restart the backend.

---

## Layer 3 (Recommended) — Pre-deploy Script Hook

Every deploy command that reaches production should run:

```bash
bash /app/backend/scripts/predeploy_check.sh
```

This performs three stages:

1. **Pytest regression** — all 73 iter42-51 tests
2. **Live-endpoint probe** — `/api/auth/health` + `/api/admin/save-health`
3. **Synthetic Trip → Halting E2E smoke** — creates a trip, edits halting,
   asserts halting_amount goes 12k → 24k end-to-end

**Exit code contract**

| Exit | Meaning |
| :-- | :-- |
| 0 | Safe to deploy |
| 1 | Regression suite failed |
| 2 | Auth pipeline unhealthy |
| 3 | Trip / Halting smoke test broke |

### Wire it in

**Emergent Deploy** — In `emergent.yml` or your deploy hook:
```yaml
pre_deploy: bash /app/backend/scripts/predeploy_check.sh
```

**GitHub Actions** — already handled by `regression-guard.yml`.

**Shell scripts** — wrap your deploy command:
```bash
bash backend/scripts/predeploy_check.sh || {
  echo "❌ Deploy blocked — regression guard failed"
  exit 1
}
your-deploy-command
```

---

## Monitoring

- **Dashboard tile** — Every Bitumen Transport user with dashboard access
  sees the current Deploy Guard status. Green tile with "Guard PASS · Safe
  to Deploy" means production is green. Rose tile with "Guard FAIL · Deploy
  BLOCKED" means the next promotion cycle will be refused.
- **API** — `GET /api/admin/deploy-readiness` returns the machine-readable
  latest result. Poll from your monitoring tool of choice.
- **Manual re-run** — `POST /api/admin/deploy-readiness/run-now` or click
  "Re-run" on the Dashboard tile forces a fresh check.

---

## Testing the guard itself

To confirm your enforcement works before you trust it in prod:

```bash
# 1. Break a critical test on purpose
sed -i 's/assert d\["ok"\] is True/assert d["ok"] is False/' \
    /app/backend/tests/test_iter48_auth_stability.py

# 2. Force the guard to re-run
curl -X POST $REACT_APP_BACKEND_URL/api/admin/deploy-readiness/run-now
sleep 30

# 3. Verify the guard now reports FAIL
curl -s $REACT_APP_BACKEND_URL/api/admin/deploy-readiness | python -m json.tool
# Expected: "status": "fail"

# 4. Verify health endpoint fails in strict mode
export REGRESSION_GUARD_STRICT=1
sudo supervisorctl restart backend
sleep 90
curl -s -o /dev/null -w "%{http_code}\n" $REACT_APP_BACKEND_URL/api/auth/health
# Expected: 503

# 5. Repair the test
git checkout /app/backend/tests/test_iter48_auth_stability.py

# 6. Re-run + verify green
curl -X POST $REACT_APP_BACKEND_URL/api/admin/deploy-readiness/run-now
sleep 30
curl -s $REACT_APP_BACKEND_URL/api/admin/deploy-readiness | python -m json.tool
```

---

## Support

If the guard blocks a deploy, look at:

1. `/tmp/deploy_readiness.json` — machine-readable result
2. Dashboard → Deploy Guard tile → last output tail (2000 chars)
3. `curl $REACT_APP_BACKEND_URL/api/admin/deploy-readiness | jq .output_tail`
4. Re-run locally: `bash /app/backend/scripts/run_regression.sh`
