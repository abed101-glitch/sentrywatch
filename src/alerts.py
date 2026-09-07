# Class 8 - real-time alerting

from __future__ import annotations

import os
import ssl
import time
import json
import smtplib
import hashlib
import threading
from email.message import EmailMessage
from datetime import datetime, timezone

import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Class 11 - the setup page can point alerts at a different chat at runtime.
# The bot token is never settable from the browser; it only ever comes from the
# environment, so a public page cannot hijack the bot.
RUNTIME = {"chat_id": None}


def set_chat_id(chat_id: str | None) -> None:
    RUNTIME["chat_id"] = (chat_id or "").strip() or None


def active_chat_id() -> str:
    return RUNTIME["chat_id"] or TELEGRAM_CHAT_ID


def bot_username() -> dict:
    """Ask Telegram who this bot is, so the page can build a t.me link."""
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not set on the server"}
    if RUNTIME.get("username"):
        return {"ok": True, "username": RUNTIME["username"]}
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe",
            timeout=HTTP_TIMEOUT,
        )
        d = r.json()
        if not d.get("ok"):
            return {"ok": False, "error": d.get("description", "getMe failed")}
        RUNTIME["username"] = d["result"]["username"]
        return {"ok": True, "username": RUNTIME["username"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def find_start(code: str) -> dict:
    """
    Look for someone who pressed Start on the bot with our one-time code.

    Telegram deep links send '/start <code>' as an ordinary message, so the
    chat id arrives without the person ever having to look it up.
    """
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not set on the server"}
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
            params={"timeout": 0, "allowed_updates": '["message"]'},
            timeout=HTTP_TIMEOUT,
        )
        d = r.json()
        if not d.get("ok"):
            desc = d.get("description", "")
            if "webhook" in desc.lower():
                desc = ("a webhook is set on this bot, so polling is blocked - "
                        "delete it or connect by chat id instead")
            return {"ok": False, "error": desc or "getUpdates failed"}

        for upd in reversed(d.get("result", [])):
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            if text in (f"/start {code}", f"/start{code}"):
                chat = msg.get("chat", {})
                return {
                    "ok": True,
                    "found": True,
                    "chat_id": str(chat.get("id")),
                    "name": chat.get("first_name") or chat.get("title") or "there",
                }
        return {"ok": True, "found": False}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def alert_config() -> dict:
    chat = active_chat_id()
    return {
        "token_configured": bool(TELEGRAM_BOT_TOKEN),
        "chat_id_set": bool(chat),
        "chat_id": (chat[:4] + "..." + chat[-3:]) if chat and len(chat) > 8 else chat,
        "source": "setup page" if RUNTIME["chat_id"] else "environment",
        "can_deliver": bool(TELEGRAM_BOT_TOKEN and chat),
    }

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

ALERT_CHANNELS = tuple(
    c.strip() for c in os.getenv("ALERT_CHANNELS", "telegram").split(",") if c.strip()
)

COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
MAX_ALERTS_PER_HOUR = int(os.getenv("MAX_ALERTS_PER_HOUR", "20"))

HTTP_TIMEOUT = 10


class AlertThrottle:

    def __init__(self, cooldown=COOLDOWN_SECONDS, max_per_hour=MAX_ALERTS_PER_HOUR):
        self.cooldown = cooldown
        self.max_per_hour = max_per_hour
        self._last_sent: dict[str, float] = {}
        self._recent: list[float] = []
        self._lock = threading.Lock()
        self.suppressed_count: dict[str, int] = {}

    def allow(self, dedup_key: str) -> tuple[bool, str]:
        now = time.time()
        with self._lock:
            self._recent = [t for t in self._recent if now - t < 3600]
            if len(self._recent) >= self.max_per_hour:
                return False, (
                    f"global cap reached ({self.max_per_hour}/hour) - "
                    "possible model drift, check the dashboard"
                )

            last = self._last_sent.get(dedup_key)
            if last is not None and now - last < self.cooldown:
                self.suppressed_count[dedup_key] = (
                    self.suppressed_count.get(dedup_key, 0) + 1
                )
                remaining = int(self.cooldown - (now - last))
                return False, (
                    f"duplicate of an alert sent {int(now - last)}s ago "
                    f"(cooldown {remaining}s remaining, "
                    f"{self.suppressed_count[dedup_key]} suppressed so far)"
                )

            self._last_sent[dedup_key] = now
            self._recent.append(now)
            return True, "ok"

    def pop_suppressed(self, dedup_key: str) -> int:
        with self._lock:
            return self.suppressed_count.pop(dedup_key, 0)


throttle = AlertThrottle()


def make_dedup_key(result: dict, tx: dict) -> str:
    account = str(
        result.get("account_id") or tx.get("account_id") or tx.get("user_id") or "global"
    )
    amount_odd = bool(result.get("z_score") or 0) and float(result.get("z_score") or 0) > 3
    velocity_odd = int(result.get("txn_count_1h") or 0) >= 10
    signals = f"{bool(result.get('ml_flagged'))}|{amount_odd}|{velocity_odd}"
    raw = f"{account}|{result.get('severity')}|{signals}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _fmt_money(v) -> str:
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _sigma_phrase(z) -> str:
    try:
        z = float(z)
    except (TypeError, ValueError):
        return ""
    direction = "above" if z >= 0 else "below"
    return f"{abs(z):.1f} sigma {direction}"


def describe_amount(result: dict, tx: dict) -> list[str]:
    lines = []
    amount = tx.get("Amount", result.get("Amount"))
    typical = result.get("account_mean")
    warm = result.get("account_warm")
    z = result.get("account_z") if warm else result.get("global_z")

    if not warm:
        n = result.get("account_n", 0)
        lines.append(
            f"This account has only {n} transactions of history, so it is "
            f"scored against the global baseline."
        )
        if z is not None:
            lines.append(f"That is {_sigma_phrase(z)} the global average.")
        return lines

    try:
        multiple = float(amount) / float(typical) if typical else None
    except (TypeError, ValueError, ZeroDivisionError):
        multiple = None

    if typical:
        lines.append(f"This account normally spends about {_fmt_money(typical)}.")

    if multiple is None:
        lines.append(f"This one is {_sigma_phrase(z)} its own baseline.")
    elif multiple >= 1.5:
        lines.append(
            f"This one is {multiple:.1f}x that - {_sigma_phrase(z)} its own baseline."
        )
    elif multiple <= 0.5:
        lines.append(
            f"This one is much smaller ({_sigma_phrase(z)} its own baseline), "
            f"so the amount itself is not the concern."
        )
    else:
        lines.append(
            f"The amount is in line with normal for this account "
            f"({_sigma_phrase(z)} its baseline)."
        )
    return lines


def format_alert(result: dict, tx: dict, suppressed: int = 0) -> dict:
    sev = str(result.get("severity", "unknown")).upper()
    amount = tx.get("Amount", result.get("Amount", "n/a"))
    account = (result.get("account_id") or tx.get("account_id")
               or tx.get("user_id") or "unknown")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    icon = {"HIGH": "[!!]", "MEDIUM": "[!]"}.get(sev, "[i]")

    lines = [
        f"{icon} *{sev} SEVERITY*",
        "",
        f"*Amount:*  {_fmt_money(amount)}",
        f"*Account:* {account}",
        f"*Time:*    {ts}",
        "",
    ]
    lines += describe_amount(result, tx)

    extras = []
    velocity = int(result.get("txn_count_1h") or 0)
    if velocity >= 10:
        extras.append(f"{velocity} transactions in the last hour (possible card testing)")
    if result.get("ml_flagged"):
        extras.append(
            f"Isolation Forest flagged it (score {result.get('ml_score')})"
        )
    drift = result.get("baseline_drift")
    if drift is not None and abs(float(drift)) > 2:
        extras.append(
            f"this account's recent spending has drifted {float(drift):.1f} sigma "
            f"from its lifetime average"
        )
    if extras:
        lines += [""] + [f"- {e}" for e in extras]

    if suppressed:
        lines += ["", f"_+{suppressed} similar events suppressed during cooldown_"]

    telegram_text = "\n".join(lines)

    subject = f"[{sev}] {_fmt_money(amount)} on account {account}"
    plain = telegram_text.replace("*", "").replace("`", "").replace("_", "")

    body_rows = "".join(
        f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
        for k, v in [
            ("Amount", _fmt_money(amount)),
            ("Account", account),
            ("Typical for this account", _fmt_money(result.get("account_mean"))
             if result.get("account_warm") else "not enough history"),
            ("Transactions in last hour", result.get("txn_count_1h", 0)),
            ("Isolation Forest", "flagged" if result.get("ml_flagged") else "clear"),
            ("Reason", result.get("reason", "n/a")),
        ]
    )
    html = (
        '<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;">'
        f'<h2 style="color:{"#c0392b" if sev == "HIGH" else "#e67e22"};margin-bottom:4px;">'
        f'{sev} severity anomaly</h2>'
        f'<p style="color:#666;margin-top:0;">{ts}</p>'
        f'<p>{" ".join(describe_amount(result, tx))}</p>'
        f'<table cellpadding="6" style="border-collapse:collapse;font-size:14px;">'
        f'{body_rows}</table>'
        + (f'<p style="color:#888;font-size:13px;">+{suppressed} similar events '
           f'suppressed during cooldown.</p>' if suppressed else "")
        + '<p style="color:#888;font-size:12px;">CSE 299 fraud detection pipeline.</p>'
        '</body></html>'
    )

    return {
        "telegram_text": telegram_text,
        "email_subject": subject,
        "email_plain": plain,
        "email_html": html,
    }


def send_telegram(text: str, chat_id: str | None = None) -> dict:
    chat_id = chat_id or active_chat_id()
    if not TELEGRAM_BOT_TOKEN:
        return {"channel": "telegram", "ok": False,
                "error": "TELEGRAM_BOT_TOKEN is not set on the server"}
    if not chat_id:
        return {"channel": "telegram", "ok": False,
                "error": "no chat id - set one on the setup page"}
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.ok:
            return {"channel": "telegram", "ok": True, "status": r.status_code}
        # Translate Telegram's codes into something a human can act on.
        code = r.status_code
        try:
            desc = r.json().get("description", "")
        except Exception:
            desc = r.text[:200]
        if code == 404:
            why = ("the bot token is not valid - it was probably revoked, or has a "
                   "stray space or quote around it. Check /getMe with the token.")
        elif code == 400 and "chat not found" in desc.lower():
            why = (f"chat {chat_id} does not exist, or you have never opened a "
                   "conversation with this bot. Message the bot once, then retry.")
        elif code == 403:
            why = "the bot is blocked by that chat, or was never started there."
        elif code == 401:
            why = "the token was rejected as unauthorised."
        elif code == 429:
            why = "Telegram is rate limiting - wait a moment and retry."
        else:
            why = desc or f"HTTP {code}"
        return {"channel": "telegram", "ok": False, "status": code,
                "error": why, "detail": desc}
    except Exception as e:
        return {"channel": "telegram", "ok": False, "error": str(e)}


def send_email(subject: str, plain: str, html: str) -> dict:
    if not SMTP_USER or not SMTP_PASS or not ALERT_EMAIL_TO:
        return {"channel": "email", "ok": False, "error": "credentials not configured"}
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL_TO
        msg.set_content(plain)
        msg.add_alternative(html, subtype="html")

        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=HTTP_TIMEOUT) as s:
            s.starttls(context=ctx)
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return {"channel": "email", "ok": True}
    except Exception as e:
        return {"channel": "email", "ok": False, "error": str(e)}


def dispatch_alert(result: dict, tx: dict, channels=None, deliver: bool = True) -> dict:
    channels = ALERT_CHANNELS if channels is None else channels
    key = make_dedup_key(result, tx)
    allowed, reason = throttle.allow(key)

    if not allowed:
        return {
            "sent": False,
            "would_send": False,
            "suppressed": True,
            "dedup_key": key,
            "suppression_reason": reason,
            "message": None,
            "results": [],
        }

    suppressed = throttle.pop_suppressed(key)
    msg = format_alert(result, tx, suppressed=suppressed)

    if not deliver:
        return {
            "sent": False,
            "would_send": True,
            "suppressed": False,
            "dedup_key": key,
            "rolled_up_events": suppressed,
            "message": msg["telegram_text"],
            "delivered_by": "n8n",
            "results": [],
        }

    results = []
    if "telegram" in channels:
        results.append(send_telegram(msg["telegram_text"]))
    if "email" in channels:
        results.append(
            send_email(msg["email_subject"], msg["email_plain"], msg["email_html"])
        )

    sent = any(r.get("ok") for r in results)
    return {
        "sent": sent,
        # would_send means "the throttle allowed it", not "it arrived".
        "would_send": True,
        "delivery_failed": not sent,
        "delivery_error": None if sent else "; ".join(
            str(r.get("error") or r.get("detail") or "") for r in results
        ).strip("; ") or "no channel delivered",
        "suppressed": False,
        "dedup_key": key,
        "rolled_up_events": suppressed,
        "message": msg["telegram_text"],
        "delivered_by": "service",
        "results": results,
    }


if __name__ == "__main__":
    import sys

    warm = {
        "severity": "high", "account_id": "ACC-1042", "account_warm": True,
        "account_mean": 380.50, "account_z": 17.4, "global_z": 17.6,
        "account_n": 214, "txn_count_1h": 2, "ml_flagged": True,
        "ml_score": -0.0812, "baseline_drift": 0.3,
        "reason": "amount z-score 17.40 vs own history",
    }
    cold = {
        "severity": "medium", "account_id": "ACC-9999", "account_warm": False,
        "account_mean": None, "account_z": None, "global_z": 4.2,
        "account_n": 7, "txn_count_1h": 1, "ml_flagged": False,
        "ml_score": 0.14, "baseline_drift": None,
        "reason": "amount z-score 4.20 vs all accounts",
    }
    testing = {
        "severity": "high", "account_id": "ACC-3311", "account_warm": True,
        "account_mean": 62.00, "account_z": -1.8, "global_z": -0.3,
        "account_n": 430, "txn_count_1h": 19, "ml_flagged": False,
        "ml_score": 0.09, "baseline_drift": 0.1,
        "reason": "19 transactions in the last hour",
    }

    if "--test" in sys.argv:
        print(json.dumps(
            dispatch_alert(warm, {"Amount": 4500.0, "Time": 51000.0,
                                  "account_id": "ACC-1042"}), indent=2))
    else:
        for label, res, tx in [
            ("WARM ACCOUNT, LARGE AMOUNT", warm, {"Amount": 4500.0, "account_id": "ACC-1042"}),
            ("COLD ACCOUNT", cold, {"Amount": 900.0, "account_id": "ACC-9999"}),
            ("CARD TESTING", testing, {"Amount": 3.0, "account_id": "ACC-3311"}),
        ]:
            print("=" * 58)
            print(label)
            print("=" * 58)
            print(format_alert(res, tx)["telegram_text"])
            print()
