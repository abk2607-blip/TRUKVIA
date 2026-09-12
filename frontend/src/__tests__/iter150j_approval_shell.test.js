/**
 * Iter150J · Approval Framework — Jest shell tests (12).
 *
 * These tests are pure module-shape / static-content checks and do not
 * spin up a live browser. They enforce:
 *   1. api.js exports axios interceptor + still returns fmtCurrency etc.
 *   2. api/approvals.js exposes the expected helpers.
 *   3. ApprovalQueue page exists.
 *   4. ApprovalDetailDialog contains required action buttons + testids.
 *   5. PendingApprovalBadge component present.
 *   6. Layout.jsx registers the `/approvals` nav item.
 *   7. App.js registers the `/approvals` route.
 *   8. api.js contains the 409 approval_required reroute branch.
 *   9. api.js recursion guard for `/approvals`.
 *  10. api.js derives entity_kind from writer URL.
 *  11. PaymentDrawer.jsx untouched — no direct approvals awareness.
 *  12. DriverPaymentDrawer.jsx untouched — no direct approvals awareness.
 */
const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), "utf8");
}

describe("Iter150J · shell contracts", () => {
  test("01 · api/approvals.js exposes lifecycle helpers", () => {
    const src = read("api/approvals.js");
    for (const fn of [
      "listApprovals", "getApproval", "pendingCount",
      "approveApproval", "rejectApproval", "withdrawApproval",
      "resubmitApproval",
    ]) {
      expect(src).toMatch(new RegExp(`export async function ${fn}`));
    }
  });

  test("02 · api/approvals.js exports label maps", () => {
    const src = read("api/approvals.js");
    expect(src).toMatch(/export const ENTITY_KIND_LABEL/);
    expect(src).toMatch(/export const STATUS_LABEL/);
  });

  test("03 · ApprovalQueue page exists and contains testids", () => {
    const src = read("pages/ApprovalQueue.jsx");
    expect(src).toMatch(/data-testid="approval-queue-page"/);
    expect(src).toMatch(/data-testid="approval-queue-status-filter"/);
    expect(src).toMatch(/data-testid="approval-queue-kind-filter"/);
    expect(src).toMatch(/data-testid="approval-queue-tbody"/);
    // Queue must NOT contain a payment-creation button.
    expect(src).not.toMatch(/create-payment|new-payment/i);
  });

  test("04 · ApprovalDetailDialog exposes approve/reject/withdraw actions", () => {
    const src = read("components/ApprovalDetailDialog.jsx");
    expect(src).toMatch(/data-testid="approval-detail-dialog"/);
    expect(src).toMatch(/data-testid="approval-detail-approve-btn"/);
    expect(src).toMatch(/data-testid="approval-detail-reject-btn"/);
    expect(src).toMatch(/data-testid="approval-detail-withdraw-btn"/);
    expect(src).toMatch(/data-testid="approval-detail-payload"/);
  });

  test("05 · PendingApprovalBadge component present", () => {
    const src = read("components/PendingApprovalBadge.jsx");
    expect(src).toMatch(/data-testid="pending-approval-badge"/);
    expect(src).toMatch(/pendingCount/);
  });

  test("06 · Layout.jsx registers nav-approvals", () => {
    const src = read("components/Layout.jsx");
    expect(src).toMatch(/testid:\s*"nav-approvals"/);
    expect(src).toMatch(/to:\s*"\/approvals"/);
    expect(src).toMatch(/PendingApprovalBadge/);
  });

  test("07 · App.js registers /approvals route", () => {
    const src = read("App.js");
    expect(src).toMatch(/import ApprovalQueue from "@\/pages\/ApprovalQueue"/);
    expect(src).toMatch(/path="\/approvals"/);
  });

  test("08 · api.js contains the 409 approval_required branch", () => {
    const src = read("api.js");
    expect(src).toMatch(/approval_required/);
    expect(src).toMatch(/_approvalRerouted/);
    expect(src).toMatch(/api\.post\("\/approvals"/);
  });

  test("09 · api.js guards against approvals-URL recursion", () => {
    const src = read("api.js");
    expect(src).toMatch(/isApprovalUrl/);
    expect(src).toMatch(/url\.includes\("\/approvals"\)/);
  });

  test("10 · api.js derives entity_kind from writer URL", () => {
    const src = read("api.js");
    expect(src).toMatch(/_deriveApprovalContext/);
    expect(src).toMatch(/_APPROVAL_ROUTE_MATCHERS/);
    // All six writer patterns present.
    for (const p of [
      /\\\/trips/, /\\\/invoices/,
      /suppliers/, /vendors/, /mechanics/, /drivers/,
    ]) {
      expect(src).toMatch(p);
    }
  });

  test("11 · PaymentDrawer.jsx remains untouched (no approvals reference)", () => {
    const src = read("components/PaymentDrawer.jsx");
    expect(src).not.toMatch(/approval|Approval/);
  });

  test("12 · DriverPaymentDrawer.jsx remains untouched (no approvals reference)", () => {
    const src = read("components/DriverPaymentDrawer.jsx");
    expect(src).not.toMatch(/approval|Approval/);
  });
});
