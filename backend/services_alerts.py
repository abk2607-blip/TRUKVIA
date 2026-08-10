"""Iter52 — Ops Alert Channel service.

Sends critical operational alerts through:
  1. Email — via Emergent-managed Resend (playbook: EMERGENT_EMAIL_KEY)
  2. WhatsApp deeplink — https://wa.me/?text=<url-encoded-message> for MANUAL share

Configurable recipients + channel toggles stored in `db.alert_config` under
_id="save_health" (extended in Iter52 with email_recipients + channels).

Alert types handled:
  - save_failures (from _evaluate_save_health_alerts)
  - auth_failures (login/session issues crossing threshold)
  - deploy_failure (regression guard flips to fail)
  - custom (from arbitrary caller)

All email templates include: module, error count, time period, date/time, and
error details — as requested by the user.
"""
import os
import logging
import urllib.parse
import httpx
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

EMAIL_BASE_URL = "https://integrations.emergentagent.com"


def _email_env():
    """Late-read env vars so tests can override without a module reload."""
    return {
        "key": os.environ.get("EMERGENT_EMAIL_KEY", ""),
        "from_name": os.environ.get("EMAIL_FROM_NAME", "Bitumen Transport"),
    }


def _fmt_time(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat((iso_ts or "").replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y · %H:%M UTC")
    except Exception:
        return iso_ts or "unknown"


def build_save_failure_email_html(alert: dict) -> str:
    """Iter52 — Compose a rich HTML email for a Save-Health alert."""
    fired_at = _fmt_time(alert.get("fired_at", ""))
    threshold = alert.get("threshold", 0)
    window_h = alert.get("window_hours", 1)
    total = alert.get("total_failures", 0)
    offenders = alert.get("top_offenders", []) or []
    recent = (alert.get("recent_errors", []) or [])[:5]

    off_rows = "".join(
        f"""<tr>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:12px">{o.get('collection','?')}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:12px">{o.get('status','?')}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:12px;text-align:right;font-weight:bold">{o.get('count',0)}</td>
            </tr>"""
        for o in offenders
    ) or '<tr><td colspan="3" style="padding:8px 12px;color:#6b7280">No offenders recorded</td></tr>'

    err_rows = "".join(
        f"""<li style="font-family:monospace;font-size:11px;padding:2px 0;color:#374151">
              <span style="color:#6b7280">{_fmt_time(r.get('ts',''))}</span> ·
              <span style="font-weight:bold">{r.get('method','?')} {r.get('path','?')[:80]}</span> ·
              <span style="color:#be123c;font-weight:bold">HTTP {r.get('status','?')}</span>
            </li>"""
        for r in recent
    ) or '<li style="color:#6b7280">No recent errors in payload</li>'

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f3f4f6;padding:24px">
      <tr><td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border:2px solid #be123c;border-radius:6px;overflow:hidden">
          <tr>
            <td style="background:#be123c;color:#fff;padding:20px 24px">
              <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;font-weight:bold;opacity:0.9">🚨 Critical Alert</div>
              <div style="font-size:22px;font-weight:bold;margin-top:4px">Save-Health Threshold Crossed</div>
              <div style="font-size:12px;opacity:0.9;margin-top:6px">{fired_at}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:24px">
              <p style="margin:0 0 12px 0;font-size:14px;color:#111827">
                <b>{total}</b> save failures logged in the last <b>{window_h}h</b> — threshold was <b>{threshold}</b>.
              </p>
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#fef2f2;padding:12px;border-radius:4px;margin:16px 0">
                <tr>
                  <td style="font-size:12px;color:#7f1d1d;line-height:1.6">
                    <b>Module:</b> Save-Health middleware<br/>
                    <b>Error count:</b> {total} failures<br/>
                    <b>Time period:</b> Last {window_h} hour(s)<br/>
                    <b>Date/Time (UTC):</b> {fired_at}
                  </td>
                </tr>
              </table>
              <h3 style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;margin:20px 0 8px 0">Top Offenders</h3>
              <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb">
                <tr style="background:#f9fafb">
                  <th align="left" style="padding:8px 12px;font-size:10px;text-transform:uppercase;color:#6b7280">Module</th>
                  <th align="left" style="padding:8px 12px;font-size:10px;text-transform:uppercase;color:#6b7280">Status</th>
                  <th align="right" style="padding:8px 12px;font-size:10px;text-transform:uppercase;color:#6b7280">Count</th>
                </tr>
                {off_rows}
              </table>
              <h3 style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;margin:20px 0 8px 0">Recent Errors</h3>
              <ul style="margin:0;padding-left:16px;list-style:disc">{err_rows}</ul>
              <p style="margin:24px 0 0 0;font-size:11px;color:#6b7280;line-height:1.5">
                This alert was sent because the failure count crossed the threshold you configured on the Dashboard.
                Adjust it under Dashboard → Save Health → Configure. Cooldown between alerts prevents spam.
              </p>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
    """


def build_generic_alert_email_html(payload: dict) -> str:
    """Generic HTML for arbitrary alert types (auth/deploy/custom)."""
    typ = payload.get("type", "custom")
    subj = payload.get("subject", "Bitumen Transport — Ops Alert")
    body = payload.get("body_html", "<p>(no body)</p>")
    fired = _fmt_time(payload.get("fired_at", datetime.now(timezone.utc).isoformat()))
    module = payload.get("module", "unknown")
    count = payload.get("error_count", 0)
    period = payload.get("time_period", "n/a")
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f3f4f6;padding:24px">
      <tr><td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border:2px solid #b45309;border-radius:6px;overflow:hidden">
          <tr>
            <td style="background:#b45309;color:#fff;padding:20px 24px">
              <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;font-weight:bold;opacity:0.9">⚠️ Ops Alert · {typ}</div>
              <div style="font-size:22px;font-weight:bold;margin-top:4px">{subj}</div>
              <div style="font-size:12px;opacity:0.9;margin-top:6px">{fired}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:24px">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#fef3c7;padding:12px;border-radius:4px;margin-bottom:16px">
                <tr><td style="font-size:12px;color:#78350f;line-height:1.6">
                  <b>Module:</b> {module}<br/>
                  <b>Error count:</b> {count}<br/>
                  <b>Time period:</b> {period}<br/>
                  <b>Date/Time (UTC):</b> {fired}
                </td></tr>
              </table>
              {body}
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
    """


def build_whatsapp_deeplink(text: str, phone: str | None = None) -> str:
    """Iter52 — Compose a wa.me deeplink URL. If phone is None, the link
    opens WhatsApp's contact picker; otherwise it targets that specific
    number. Numbers must include the country code, digits only.
    Example: build_whatsapp_deeplink("Alert!", "919999999999")"""
    enc = urllib.parse.quote(text)
    if phone:
        clean = "".join(ch for ch in str(phone) if ch.isdigit())
        return f"https://wa.me/{clean}?text={enc}"
    return f"https://wa.me/?text={enc}"


def build_save_failure_whatsapp_text(alert: dict) -> str:
    """Compact plain-text summary suitable for WhatsApp."""
    off = alert.get("top_offenders", []) or []
    off_lines = "\n".join(f"  • {o.get('collection','?')} · HTTP {o.get('status','?')} · {o.get('count',0)}"
                          for o in off[:5])
    return (
        "🚨 *Save-Health Alert — Bitumen Transport*\n\n"
        f"*{alert.get('total_failures',0)} save failures* in the last "
        f"{alert.get('window_hours',1)}h (threshold: {alert.get('threshold',0)}).\n\n"
        f"*Time:* {_fmt_time(alert.get('fired_at',''))}\n\n"
        f"*Top offenders:*\n{off_lines or '(none)'}\n\n"
        "Open the Dashboard → Save Health tile for details + acknowledge."
    )


async def send_alert_email(recipients: list[str], subject: str, html: str) -> dict:
    """Fire the email through the Emergent proxy. Non-blocking. Returns a dict
    with per-recipient status (success/failure). Never raises."""
    env = _email_env()
    if not env["key"]:
        return {"ok": False, "reason": "EMERGENT_EMAIL_KEY not configured", "sent": []}
    if not recipients:
        return {"ok": False, "reason": "No recipients configured", "sent": []}
    sent = []
    errors = []
    async with httpx.AsyncClient(timeout=15) as client:
        for r in recipients:
            payload = {
                "to": [r],
                "subject": subject,
                "html": html,
                "from_name": env["from_name"],
            }
            try:
                resp = await client.post(
                    f"{EMAIL_BASE_URL}/api/v1/email/send",
                    headers={"X-Email-Key": env["key"]},
                    json=payload,
                )
                resp.raise_for_status()
                sent.append({"to": r, "email_id": resp.json().get("id"), "status": "sent"})
            except httpx.HTTPStatusError as e:
                errors.append({"to": r, "status": e.response.status_code, "detail": e.response.text[:200]})
                logger.error(f"Alert email failed for {r}: {e.response.status_code} {e.response.text}")
            except Exception as e:
                errors.append({"to": r, "detail": str(e)[:200]})
                logger.error(f"Alert email exception for {r}: {e}")
    return {"ok": len(errors) == 0, "sent": sent, "errors": errors}
