# -*- coding: utf-8 -*-
"""
MAIL OTP BOT - BAN 1 FILE DUY NHAT
==================================
Bot Telegram mail tam thoi & nhan OTP, CHI ADMIN DUOC DUNG.

Cach chay:
    pip install python-telegram-bot httpx beautifulsoup4 flask
    python mail_otp_bot.py
"""

# ═══════════════════════════════════════════════════════════════════
#  CAU HINH - token & admin da tich hop san theo yeu cau
#  ⚠️  Token nay da dan trong khung chat 2 lan -> cuc ky nen vao
#  @BotFather -> /revoke de thu hoi, roi thay token MOI vao day.
#  Khong gui file nay cho bat ky ai.
# ═══════════════════════════════════════════════════════════════════
BOT_TOKEN = ""  # -> nap tu bien moi truong BOT_TOKEN hoac file token.txt (xem _load_token)
ADMIN_ID = 5932089197
ADMIN_USERNAME = "tmmedia"

POLL_INTERVAL = 5
POLL_MIN_INTERVAL = 3
POLL_MAX_INTERVAL = 120
DEFAULT_PROVIDER = "mail.tm"
NOTIFY_ENABLED = True
OTP_ONLY_MODE = False
HTTP_TIMEOUT = 20
MAX_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DATA_DIR = "data"
DB_PATH = "data/mailbot.db"
LOG_PATH = "data/bot.log"
MAX_BODY_CHARS = 2500
MAX_SUBJECT_CHARS = 120

# ── Thu vien ─────────────────────────────────────────────────────
import asyncio
import atexit
import functools
import html
import json
import logging
import os
import random
import re
import sqlite3
import string
import time
import traceback
from dataclasses import dataclass, field
from email.header import decode_header
from pathlib import Path

import httpx
try:
    from flask import Flask, jsonify, request as _rq
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      ReplyKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, ConversationHandler, MessageHandler,
                          filters)


def _load_token():
    """Lay BOT_TOKEN theo thu tu uu tien:
    1. Bien moi truong BOT_TOKEN (dung khi deploy cloud nhu Render)
    2. File token.txt cung thu muc (dung local, file nay KHONG up len git)
    """
    tok = os.environ.get("BOT_TOKEN", "").strip()
    if tok:
        return tok
    tf = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "token.txt")
    try:
        with open(tf, encoding="utf-8") as f:
            tok = f.read().strip()
            if tok:
                return tok
    except OSError:
        pass
    return ""


# ══════════════ 1. TACH OTP ══════════════
# -*- coding: utf-8 -*-
"""Tach ma OTP tu tieu de / noi dung mail."""


def decode_mime_header(value):
    """Giai ma tieu de dang =?UTF-8?B?...?= ve chuoi doc duoc."""
    if not value:
        return ""
    if not isinstance(value, str):
        value = str(value)
    try:
        parts = []
        for chunk, enc in decode_header(value):
            if isinstance(chunk, bytes):
                try:
                    parts.append(chunk.decode(enc or "utf-8", errors="replace"))
                except Exception:
                    parts.append(chunk.decode("utf-8", errors="replace"))
            else:
                parts.append(chunk)
        return "".join(parts).strip()
    except Exception:
        return value


def html_to_text(html_content):
    """Chuyen HTML ve text thuong."""
    if not html_content:
        return ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html_content)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Tu khoa goi y OTP -> trong so. Cang gan ma OTP thi cang chac chan.
OTP_KEYWORDS = [
    (r"mã\s*xác\s*nhận", 6),
    (r"mã\s*xác\s*thực", 6),
    (r"verification\s*code", 6),
    (r"mã\s*kích\s*hoạt", 5),
    (r"security\s*code", 5),
    (r"mã\s*bảo\s*mật", 5),
    (r"\botp\b", 5),
    (r"xác\s*minh", 3),
    (r"verify", 3),
    (r"\bcode\b", 3),
    (r"\bpin\b", 3),
    (r"kích\s*hoạt", 2),
    (r"mã\s*số", 2),
]


def extract_otp_candidates(text):
    """Tra ve [(ma_otp, diem)] da sap xep giam dan theo do tin cay."""
    if not text:
        return []
    text = str(text)
    found = []
    for m in re.finditer(r"\d{4,8}", text):
        code = m.group(0)
        if len(set(code)) == 1:
            continue  # bo 111111, 000000...
        window = text[max(0, m.start() - 90): m.end() + 90].lower()
        score = 0
        for pattern, weight in OTP_KEYWORDS:
            if re.search(pattern, window):
                score += weight
        if len(code) == 6:
            score += 2
        elif len(code) in (4, 5):
            score += 1
        # phat khi so nam giua chu cai (kieu ma don hang ABC123456)
        before = text[m.start() - 1] if m.start() > 0 else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if before.isalpha() or after.isalpha():
            score -= 3
        found.append((code, score, m.start()))
    found.sort(key=lambda x: (-x[1], x[2]))
    out, seen = [], set()
    for code, score, _pos in found:
        if code not in seen:
            seen.add(code)
            out.append((code, score))
    return out


def extract_best_otp(text):
    """Tra ve (ma_otp_tot_nhat | None, danh_sach_ung_vien)."""
    cands = extract_otp_candidates(text)
    if not cands:
        return None, []
    best, best_score = cands[0]
    # diem <= 0: khong du tin cay (so dinh vao chu cai, hoac khong co goi y nao)
    if best_score <= 0:
        return None, cands[:5]
    return best, cands[:5]

# ══════════════ 2. LUU TRU SQLITE ══════════════
# -*- coding: utf-8 -*-
"""Luu tru SQLite: hop thu, tin nhan da thay, cai dat, thong ke."""



def _conn():
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS mailboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backend TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                login TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                password TEXT DEFAULT '',
                token TEXT DEFAULT '',
                extra TEXT DEFAULT '{}',
                label TEXT DEFAULT '',
                is_active INTEGER DEFAULT 0,
                notify INTEGER DEFAULT 1,
                created_at TEXT DEFAULT '',
                last_check TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS seen_messages (
                mailbox_id INTEGER NOT NULL,
                provider_msg_id TEXT NOT NULL,
                PRIMARY KEY (mailbox_id, provider_msg_id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS otp_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT DEFAULT '',
                otp TEXT DEFAULT '',
                sender TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            );
            """
        )


# ------------------------------ mailboxes ------------------------------
def _row_to_dict(row):
    return dict(row) if row else None


def add_mailbox(creds, label=""):
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO mailboxes
               (backend, address, login, domain, password, token, extra, label,
                is_active, notify, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?)""",
            (creds.backend, creds.address, creds.login, creds.domain,
             creds.password, creds.token, json.dumps(creds.extra),
             label or "", time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        return cur.lastrowid


def get_mailbox(mb_id):
    with _conn() as c:
        return _row_to_dict(c.execute(
            "SELECT * FROM mailboxes WHERE id = ?", (mb_id,)).fetchone())


def get_mailbox_by_address(address):
    with _conn() as c:
        return _row_to_dict(c.execute(
            "SELECT * FROM mailboxes WHERE address = ?", (address,)).fetchone())


def list_mailboxes():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM mailboxes ORDER BY id DESC").fetchall()]


def get_active_mailbox():
    with _conn() as c:
        return _row_to_dict(c.execute(
            "SELECT * FROM mailboxes WHERE is_active = 1").fetchone())


def set_active(mb_id):
    with _conn() as c:
        c.execute("UPDATE mailboxes SET is_active = 0")
        c.execute("UPDATE mailboxes SET is_active = 1 WHERE id = ?", (mb_id,))


def update_mailbox_token(mb_id, token):
    with _conn() as c:
        c.execute("UPDATE mailboxes SET token = ? WHERE id = ?",
                  (token, mb_id))


def update_mailbox_extra(mb_id, extra):
    with _conn() as c:
        c.execute("UPDATE mailboxes SET extra = ? WHERE id = ?",
                  (json.dumps(extra or {}), mb_id))


def update_last_check(mb_id):
    with _conn() as c:
        c.execute("UPDATE mailboxes SET last_check = ? WHERE id = ?",
                  (time.strftime("%Y-%m-%d %H:%M:%S"), mb_id))


def set_notify(mb_id, on):
    with _conn() as c:
        c.execute("UPDATE mailboxes SET notify = ? WHERE id = ?",
                  (1 if on else 0, mb_id))


def rename_mailbox(mb_id, label):
    with _conn() as c:
        c.execute("UPDATE mailboxes SET label = ? WHERE id = ?",
                  (label, mb_id))


def delete_mailbox(mb_id):
    with _conn() as c:
        c.execute("DELETE FROM seen_messages WHERE mailbox_id = ?", (mb_id,))
        c.execute("DELETE FROM mailboxes WHERE id = ?", (mb_id,))
        # neu xoa hop dang active thi chon hop moi nhat lam active
        row = c.execute(
            "SELECT id FROM mailboxes ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE mailboxes SET is_active = 0")
            c.execute("UPDATE mailboxes SET is_active = 1 WHERE id = ?",
                      (row["id"],))


def delete_all_mailboxes():
    with _conn() as c:
        c.execute("DELETE FROM seen_messages")
        c.execute("DELETE FROM mailboxes")


# ------------------------------ seen ------------------------------
def is_seen(mb_id, provider_msg_id):
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM seen_messages WHERE mailbox_id = ? AND provider_msg_id = ?",
            (mb_id, str(provider_msg_id))).fetchone()
        return row is not None


def mark_seen(mb_id, provider_msg_id):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen_messages (mailbox_id, provider_msg_id)"
            " VALUES (?, ?)", (mb_id, str(provider_msg_id)))


# ------------------------------ settings ------------------------------
def get_setting(key, default=""):
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?",
                        (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with _conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)))


# ------------------------------ stats ------------------------------
def incr_stat(key, n=1):
    with _conn() as c:
        c.execute(
            "INSERT INTO stats (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = value + ?",
            (key, n, n))


def get_stat(key):
    with _conn() as c:
        row = c.execute("SELECT value FROM stats WHERE key = ?",
                        (key,)).fetchone()
        return row["value"] if row else 0


def get_all_stats():
    with _conn() as c:
        return {r["key"]: r["value"] for r in
                c.execute("SELECT key, value FROM stats").fetchall()}


# ------------------------------ otp history ------------------------------
def add_otp_history(address, otp, sender):
    with _conn() as c:
        c.execute(
            "INSERT INTO otp_history (address, otp, sender, created_at)"
            " VALUES (?, ?, ?, ?)",
            (address, otp, sender or "",
             time.strftime("%Y-%m-%d %H:%M:%S")))
        # chi giu 200 OTP gan nhat
        c.execute(
            "DELETE FROM otp_history WHERE id NOT IN "
            "(SELECT id FROM otp_history ORDER BY id DESC LIMIT 200)")


def get_otp_history(limit=15):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM otp_history ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]


def clear_otp_history():
    with _conn() as c:
        c.execute("DELETE FROM otp_history")

# ══════════════ 3. BACKEND MAIL (failover) ══════════════
# -*- coding: utf-8 -*-
"""
Cac backend mail tam thoi voi co che failover tu dong.
- mail.tm   : tai khoan co mat khau, giu mail lau nhat (uu tien)
- guerrilla : tao nhanh, khong can mat khau
- 1secmail  : tao nhanh, khong can mat khau
"""




class AuthError(Exception):
    """Token dang nhap het han, can dang nhap lai."""


class BackendError(Exception):
    """Loi nghiep vu tu provider (ten da ton tai, sai pass...)."""


@dataclass
class MailboxCreds:
    backend: str
    address: str
    login: str = ""
    domain: str = ""
    password: str = ""
    token: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class MailItem:
    msg_id: str
    sender: str = ""
    subject: str = ""
    date: str = ""
    preview: str = ""
    body_text: str = ""
    body_html: str = ""


class MailBackend:
    name = "base"
    display = "Base"
    supports_password = False
    supports_custom_domain = True
    note = ""

    def _client(self):
        return httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )

    async def _request(self, method, url, **kwargs):
        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                async with self._client() as client:
                    resp = await client.request(method, url, **kwargs)
                    return resp
            except Exception as exc:  # loi mang -> thu lai
                last_err = exc
                await asyncio.sleep(1 + attempt)
        raise last_err

    async def domains(self):
        raise NotImplementedError

    async def create_random(self):
        raise NotImplementedError

    async def create_account(self, username, password, domain):
        raise NotImplementedError

    async def login(self, address, password=""):
        raise NotImplementedError

    async def list_messages(self, creds):
        raise NotImplementedError

    async def read_message(self, creds, msg_id):
        raise NotImplementedError

    async def check_health(self):
        """Tra ve (ok: bool, ms: int, ghi_chu: str)."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
class OneSecMailBackend(MailBackend):
    name = "1secmail"
    display = "1secmail"
    supports_password = False
    note = "Tao cuc nhanh, khong can mat khau. Mail tu xoa sau vai gio."
    API = "https://www.1secmail.com/api/v1/"
    DOMAINS = [
        "1secmail.com", "1secmail.net", "1secmail.org",
        "laafd.com", "vjuum.com", "txcct.com",
        "wwjmp.com", "esiix.com", "yoggm.com",
    ]

    async def domains(self):
        # sap xep domain ngan nhat truoc -> de nho
        return sorted(self.DOMAINS, key=lambda d: (len(d), d))

    @staticmethod
    def _split(address):
        login, domain = address.strip().lower().split("@", 1)
        return login, domain

    async def create_random(self):
        resp = await self._request("GET", self.API,
                                   params={"action": "genRandomMailbox", "count": 1})
        addr = resp.json()[0]
        login, domain = self._split(addr)
        return MailboxCreds(backend=self.name, address=addr,
                            login=login, domain=domain)

    async def create_account(self, username, password, domain):
        username = username.strip().lower()
        addr = f"{username}@{domain}"
        login, domain = self._split(addr)
        return MailboxCreds(backend=self.name, address=addr,
                            login=login, domain=domain)

    async def login(self, address, password=""):
        login, domain = self._split(address)
        return MailboxCreds(backend=self.name, address=address.strip().lower(),
                            login=login, domain=domain)

    async def list_messages(self, creds):
        resp = await self._request(
            "GET", self.API,
            params={"action": "getMessages", "login": creds.login,
                    "domain": creds.domain})
        items = []
        data = resp.json()
        if isinstance(data, list):
            for m in data:
                items.append(MailItem(
                    msg_id=str(m.get("id")),
                    sender=m.get("from", ""),
                    subject=decode_mime_header(m.get("subject", "")),
                    date=m.get("date", ""),
                ))
        return items

    async def read_message(self, creds, msg_id):
        resp = await self._request(
            "GET", self.API,
            params={"action": "readMessage", "login": creds.login,
                    "domain": creds.domain, "id": msg_id})
        d = resp.json()
        body_text = d.get("textBody") or ""
        if not body_text.strip():
            body_text = html_to_text(d.get("htmlBody") or d.get("body") or "")
        return MailItem(
            msg_id=str(d.get("id", msg_id)),
            sender=d.get("from", ""),
            subject=decode_mime_header(d.get("subject", "")),
            date=d.get("date", ""),
            body_text=body_text,
            body_html=d.get("htmlBody") or "",
        )

    async def check_health(self):
        t0 = time.perf_counter()
        try:
            resp = await self._request(
                "GET", self.API,
                params={"action": "getMessages", "login": "healthcheck",
                        "domain": "1secmail.com"})
            ok = resp.status_code == 200
            return ok, int((time.perf_counter() - t0) * 1000), \
                "OK" if ok else f"HTTP {resp.status_code}"
        except Exception as exc:
            return False, int((time.perf_counter() - t0) * 1000), str(exc)[:80]


# ---------------------------------------------------------------------------
class MailTmBackend(MailBackend):
    name = "mail.tm"
    display = "mail.tm"
    supports_password = True
    note = "Co mat khau, giu mail lau nhat. Domain thay doi theo dot."
    API = "https://api.mail.tm"

    async def domains(self):
        resp = await self._request("GET", f"{self.API}/domains")
        data = resp.json()
        members = data.get("hydra:member", []) if isinstance(data, dict) else []
        return [d["domain"] for d in members if d.get("isActive")]

    def _headers(self, creds):
        return {"Authorization": f"Bearer {creds.token}"}

    async def _get_token(self, address, password):
        resp = await self._request("POST", f"{self.API}/token",
                                   json={"address": address, "password": password})
        if resp.status_code in (401, 422):
            raise BackendError("Sai email hoac mat khau.")
        if resp.status_code != 200:
            raise BackendError(f"mail.tm loi {resp.status_code}.")
        d = resp.json()
        return d["token"], d.get("id", "")

    async def create_account(self, username, password, domain):
        address = f"{username.strip().lower()}@{domain}"
        resp = await self._request("POST", f"{self.API}/accounts",
                                   json={"address": address, "password": password})
        if resp.status_code == 422:
            raise BackendError("Ten mail da ton tai, thu ten khac.")
        if resp.status_code not in (200, 201):
            raise BackendError(f"mail.tm loi {resp.status_code} khi tao tai khoan.")
        acc = resp.json()
        token, _aid = await self._get_token(address, password)
        login = address.split("@", 1)[0]
        return MailboxCreds(backend=self.name, address=address, login=login,
                            domain=domain, password=password, token=token,
                            extra={"account_id": acc.get("id", "")})

    async def login(self, address, password=""):
        address = address.strip().lower()
        token, aid = await self._get_token(address, password)
        login, domain = address.split("@", 1)
        return MailboxCreds(backend=self.name, address=address, login=login,
                            domain=domain, password=password, token=token,
                            extra={"account_id": aid})

    async def relogin(self, creds):
        """Dang nhap lai khi token het han, giu nguyen thong tin khac."""
        if not creds.password:
            raise AuthError("Khong co mat khau de dang nhap lai.")
        fresh = await self.login(creds.address, creds.password)
        creds.token = fresh.token
        creds.extra.update(fresh.extra)
        return creds

    async def list_messages(self, creds):
        resp = await self._request("GET", f"{self.API}/messages",
                                   headers=self._headers(creds))
        if resp.status_code == 401:
            raise AuthError("Token het han.")
        data = resp.json()
        members = data.get("hydra:member", []) if isinstance(data, dict) else []
        items = []
        for m in members:
            frm = m.get("from") or {}
            items.append(MailItem(
                msg_id=str(m.get("id")),
                sender=frm.get("address", "") if isinstance(frm, dict) else "",
                subject=decode_mime_header(m.get("subject", "")),
                date=m.get("createdAt", ""),
                preview=m.get("intro", ""),
            ))
        return items

    async def read_message(self, creds, msg_id):
        resp = await self._request("GET", f"{self.API}/messages/{msg_id}",
                                   headers=self._headers(creds))
        if resp.status_code == 401:
            raise AuthError("Token het han.")
        d = resp.json()
        frm = d.get("from") or {}
        text = d.get("text") or ""
        html_parts = d.get("html") or []
        if isinstance(html_parts, str):
            html_parts = [html_parts]
        body_html = "\n".join(html_parts)
        if not text.strip() and body_html.strip():
            text = html_to_text(body_html)
        return MailItem(
            msg_id=str(d.get("id", msg_id)),
            sender=frm.get("address", "") if isinstance(frm, dict) else "",
            subject=decode_mime_header(d.get("subject", "")),
            date=d.get("createdAt", ""),
            preview=d.get("intro", ""),
            body_text=text,
            body_html=body_html,
        )

    async def check_health(self):
        t0 = time.perf_counter()
        try:
            resp = await self._request("GET", f"{self.API}/domains")
            ok = resp.status_code == 200
            return ok, int((time.perf_counter() - t0) * 1000), \
                "OK" if ok else f"HTTP {resp.status_code}"
        except Exception as exc:
            return False, int((time.perf_counter() - t0) * 1000), str(exc)[:80]


# ---------------------------------------------------------------------------
class GuerrillaBackend(MailBackend):
    name = "guerrilla"
    display = "Guerrilla Mail"
    supports_password = False
    supports_custom_domain = False
    note = "Tao cuc nhanh, khong chon duoc domain."
    API = "https://api.guerrillamail.com/ajax.php"

    def _base_params(self):
        return {"ip": "127.0.0.1", "agent": "Mozilla/5.0"}

    async def domains(self):
        return []  # guerrilla tu gan domain ngau nhien

    async def _new_address(self, params):
        resp = await self._request("GET", self.API, params=params)
        d = resp.json()
        addr = d["email_addr"]
        _login, domain = addr.split("@", 1)
        return MailboxCreds(
            backend=self.name, address=addr, login=d.get("alias", ""),
            domain=domain,
            extra={"sid_token": d["sid_token"], "seq": 0})

    async def create_random(self):
        p = {"f": "get_email_address"}
        p.update(self._base_params())
        return await self._new_address(p)

    async def create_account(self, username, password, domain):
        p = {"f": "set_email_user",
             "email_user": username.strip().lower().replace(" ", "")}
        p.update(self._base_params())
        return await self._new_address(p)

    async def login(self, address, password=""):
        raise BackendError("Guerrilla khong ho tro dang nhap lai, hay tao mail moi.")

    async def list_messages(self, creds):
        sid = (creds.extra or {}).get("sid_token", "")
        seq = (creds.extra or {}).get("seq", 0)
        p = {"f": "check_email", "seq": seq, "sid_token": sid}
        p.update(self._base_params())
        resp = await self._request("GET", self.API, params=p)
        d = resp.json()
        creds.extra["seq"] = d.get("seq", seq)
        items = []
        for m in d.get("list", []):
            items.append(MailItem(
                msg_id=str(m.get("mail_id")),
                sender=m.get("mail_from", ""),
                subject=decode_mime_header(m.get("mail_subject", "")),
                date=m.get("mail_date", ""),
                preview=m.get("mail_excerpt", ""),
                body_text=m.get("mail_body", ""),
            ))
        return items

    async def read_message(self, creds, msg_id):
        sid = (creds.extra or {}).get("sid_token", "")
        p = {"f": "fetch_email", "email_id": msg_id, "sid_token": sid}
        p.update(self._base_params())
        resp = await self._request("GET", self.API, params=p)
        d = resp.json()
        body = d.get("mail_body", "") or ""
        return MailItem(
            msg_id=str(d.get("mail_id", msg_id)),
            sender=d.get("mail_from", ""),
            subject=decode_mime_header(d.get("mail_subject", "")),
            date=d.get("mail_date", ""),
            body_text=body if "\n" in body or "<" not in body else html_to_text(body),
            body_html=body if "<" in body else "",
        )

    async def check_health(self):
        t0 = time.perf_counter()
        try:
            p = {"f": "get_email_address"}
            p.update(self._base_params())
            resp = await self._request("GET", self.API, params=p)
            ok = resp.status_code == 200 and "email_addr" in resp.json()
            return ok, int((time.perf_counter() - t0) * 1000), \
                "OK" if ok else f"HTTP {resp.status_code}"
        except Exception as exc:
            return False, int((time.perf_counter() - t0) * 1000), str(exc)[:80]


# ---------------------------------------------------------------------------
class BackendManager:
    def __init__(self):
        self.backends = {
            "mail.tm": MailTmBackend(),
            "guerrilla": GuerrillaBackend(),
            "1secmail": OneSecMailBackend(),
        }
        # thu tu uu tien: ben nhat truoc
        self.priority = ["mail.tm", "guerrilla", "1secmail"]

    def get(self, name):
        return self.backends[name]

    def names(self):
        return list(self.backends.keys())

    def display_name(self, name):
        return self.backends[name].display

    async def create_random(self, preferred=None):
        """Tao mail ngau nhien, tu dong doi provider khac khi loi."""
        order = []
        if preferred in self.backends:
            order.append(preferred)
        order += [b for b in self.priority if b != preferred]
        last_err = None
        for name in order:
            try:
                creds = await self.backends[name].create_random()
                return creds, name
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"Tat ca provider deu loi: {last_err}")

    async def health_all(self):
        out = {}
        for name, be in self.backends.items():
            try:
                out[name] = await be.check_health()
            except Exception as exc:
                out[name] = (False, 0, str(exc)[:80])
        return out


manager = BackendManager()


# ══════════════ V5 PRO: DUOI DEP + SUC KHOE PROVIDER ══════════════
# Danh sach duoi "dep" duoc uu tien hien thi dau tien (co ⭐)
PRETTY_DOMAINS = [
    "laafd.com", "vjuum.com", "txcct.com", "wwjmp.com", "esiix.com",
    "yoggm.com", "guerrillamail.com", "grr.la", "sharklasers.com",
    "guerrillamail.net", "guerrillamail.org",
]

def pretty_first(domains):
    """Dua duoi dep len dau, giu nguyen thu tu con lai."""
    ps = [d for d in domains if d in PRETTY_DOMAINS]
    rest = [d for d in domains if d not in PRETTY_DOMAINS]
    return ps + rest


# Theo doi suc khoe provider: fail lien tiep >= 3 -> nghi 5 phut
PROV_HEALTH = {}

def prov_healthy(name):
    h = PROV_HEALTH.get(name)
    if not h:
        return True
    return not (h["fails"] >= 3 and time.time() < h["until"])

def prov_ok(name):
    PROV_HEALTH.pop(name, None)

def prov_fail(name):
    h = PROV_HEALTH.setdefault(name, {"fails": 0, "until": 0})
    h["fails"] += 1
    if h["fails"] >= 3:
        h["until"] = time.time() + 300
        logger.warning("Provider %s tam nghi 5 phut (fail %d lan lien tiep).",
                       name, h["fails"])


async def safe_list_messages(creds, mb_id):
    """Lay mail co retry + backoff; danh dau provider yeu khi that bai."""
    last = None
    for attempt in range(3):
        try:
            items = await fetch_items(creds, mb_id)
            prov_ok(creds.backend)
            return items
        except Exception as exc:
            last = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    prov_fail(creds.backend)
    raise last


def creds_from_row(row):
    """Dung thong tin hop thu tu DB."""
    try:
        extra = json.loads(row.get("extra") or "{}")
    except Exception:
        extra = {}
    return MailboxCreds(
        backend=row["backend"], address=row["address"],
        login=row.get("login") or "", domain=row.get("domain") or "",
        password=row.get("password") or "", token=row.get("token") or "",
        extra=extra if isinstance(extra, dict) else {},
    )

# ══════════════ 4. BAN PHIM ══════════════
# -*- coding: utf-8 -*-
"""Ban phim menu chinh va cac ban phim inline."""


def main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⚡ Tạo Mail Nhanh"), KeyboardButton("🔐 Tạo Tài Khoản")],
            [KeyboardButton("📦 Tạo nhiều mail")],
            [KeyboardButton("🔑 Đăng Nhập"), KeyboardButton("📥 Check OTP")],
            [KeyboardButton("📧 Hộp Thư Của Tôi"), KeyboardButton("📬 Danh Sách Mail")],
            [KeyboardButton("🔍 Tìm Kiếm"), KeyboardButton("📊 Thống Kê")],
            [KeyboardButton("🌐 Đổi Provider"), KeyboardButton("⚙️ Cài Đặt")],
            [KeyboardButton("🖥️ Web Dashboard")],
            [KeyboardButton("📖 Hướng Dẫn"), KeyboardButton("📤 Xuất File")],
            [KeyboardButton("🕘 Lịch sử OTP"), KeyboardButton("💾 Sao lưu")],
        ],
        resize_keyboard=True,
    )


def cancel_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("❌ Hủy")]], resize_keyboard=True, one_time_keyboard=True
    )


def providers_kb(prefix, only=None):
    """prefix: 'cr_prov' | 'lg_prov' | 'set_provider'."""
    names = only or manager.names()
    rows = []
    for n in names:
        rows.append([InlineKeyboardButton(
            f"🌐 {manager.display_name(n)}", callback_data=f"{prefix}:{n}")])
    rows.append([InlineKeyboardButton("❌ Hủy", callback_data="noop")])
    return InlineKeyboardMarkup(rows)


def domains_kb(items):
    """items: [(domain, nhan_hien_thi)]."""
    rows = []
    row = []
    for domain, label in items:
        row.append(InlineKeyboardButton(label, callback_data=f"cr_dom:{domain}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Hủy", callback_data="noop")])
    return InlineKeyboardMarkup(rows)


def after_create_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check OTP ngay", callback_data="check_now"),
         InlineKeyboardButton("📬 Danh sách mail", callback_data="mb_list")],
        [InlineKeyboardButton("➕ Tạo thêm 5 mail", callback_data="batch:5"),
         InlineKeyboardButton("➕ Tạo thêm 10 mail", callback_data="batch:10")],
    ])


def inbox_kb(tokens):
    """tokens: [(cache_token, nhan_ngan)]."""
    rows = []
    for tok, label in tokens:
        rows.append([InlineKeyboardButton(f"✉️ {label}", callback_data=f"view:{tok}")])
    rows.append([InlineKeyboardButton("🔄 Refresh", callback_data="check_now"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def message_kb(tok, has_otp, mb_id):
    rows = []
    if has_otp:
        rows.append([InlineKeyboardButton("🔑 Lấy OTP riêng", callback_data=f"otp:{tok}")])
    rows.append([InlineKeyboardButton("📥 Check OTP", callback_data="check_now"),
                 InlineKeyboardButton("📬 Danh sách", callback_data="mb_list")])
    rows.append([InlineKeyboardButton("🔕 Tắt TB hòm này",
                                      callback_data=f"mb_notify:{mb_id}")])
    return InlineKeyboardMarkup(rows)


def mailbox_list_kb(mailboxes, active_id):
    rows = []
    for mb in mailboxes:
        mark = "● " if mb["id"] == active_id else ""
        label = mb["label"] or mb["address"]
        if len(label) > 34:
            label = label[:33] + "…"
        rows.append([InlineKeyboardButton(
            f"{mark}📧 {label}", callback_data=f"mb:{mb['id']}")])
    rows.append([InlineKeyboardButton("➕ Tạo mail mới", callback_data="quick_create"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    rows.append([InlineKeyboardButton("🔄 Quét tất cả", callback_data="mb_scanall"),
                 InlineKeyboardButton("🗑️ Xóa tất cả", callback_data="mb_delall")])
    return InlineKeyboardMarkup(rows)


def mailbox_detail_kb(mb_id, is_active, notify_on):
    rows = [
        [InlineKeyboardButton("📥 Check OTP", callback_data=f"mb_check:{mb_id}")],
        [InlineKeyboardButton("🔑 Xem mật khẩu", callback_data=f"mb_pass:{mb_id}")],
        [InlineKeyboardButton("🔕 Tắt thông báo" if notify_on else "🔔 Bật thông báo",
                              callback_data=f"mb_notify:{mb_id}"),
         InlineKeyboardButton("✏️ Đổi tên", callback_data=f"mb_rename:{mb_id}")],
        [InlineKeyboardButton("🗑️ Xóa hòm thư", callback_data=f"mb_del:{mb_id}")],
    ]
    if not is_active:
        rows.insert(1, [InlineKeyboardButton("✅ Đặt làm hòm chính",
                                             callback_data=f"mb_active:{mb_id}")])
    rows.append([InlineKeyboardButton("↩ Danh sách", callback_data="mb_list"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def confirm_delete_kb(mb_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Xóa luôn", callback_data=f"mb_del_yes:{mb_id}"),
         InlineKeyboardButton("↩ Giữ lại", callback_data=f"mb:{mb_id}")],
    ])


def confirm_delete_all_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Xóa hết luôn", callback_data="mb_delall_yes"),
         InlineKeyboardButton("↩ Giữ lại", callback_data="mb_list")],
    ])


def settings_kb(notify_global, interval, default_provider, otp_only,
                short_domain, digest_mode=True):
    rows = [
        [InlineKeyboardButton(
            f"🔔 TB tự động: {'BẬT' if notify_global else 'TẮT'}",
            callback_data="set:notify")],
        [InlineKeyboardButton(
            f"⚡ Chỉ gửi OTP: {'BẬT' if otp_only else 'TẮT'}",
            callback_data="set:otponly")],
        [InlineKeyboardButton(
            f"📦 Gom thông báo (chống spam): {'BẬT' if digest_mode else 'TẮT'}",
            callback_data="set:digest")],
        [InlineKeyboardButton(
            f"⭐ Domain ngắn gọn: {'BẬT' if short_domain else 'TẮT'}",
            callback_data="set:shortdomain")],
        [InlineKeyboardButton(f"⏱️ Quét mỗi {interval}s",
                              callback_data="noop")],
    ]
    int_row = []
    for sec in (3, 5, 10, 30, 60):
        mark = "✓" if sec == interval else ""
        int_row.append(InlineKeyboardButton(f"{mark}{sec}s",
                                            callback_data=f"set:interval:{sec}"))
    rows.append(int_row)
    prov_row = []
    for n in manager.names():
        mark = "✓" if n == default_provider else ""
        prov_row.append(InlineKeyboardButton(
            f"{mark}{manager.display_name(n)}",
            callback_data=f"set:provider:{n}"))
    rows.append(prov_row)
    rows.append([InlineKeyboardButton("💾 Sao lưu dữ liệu",
                                      callback_data="set:backup")])
    rows.append([InlineKeyboardButton("🔔 Test thông báo",
                                      callback_data="set:testnotify")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

# ══════════════ 5. BOT CHINH ══════════════
# -*- coding: utf-8 -*-
"""
Mail OTP Bot - bot Telegram mail tam thoi & nhan OTP, CHI ADMIN DUOC DUNG.

Chay:  python bot.py   (dang nhap token trong py truoc)
"""



# ---------------------------------------------------------------- logging
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("mailbot")

START_TIME = time.time()

LOCK_PATH = Path(DATA_DIR) / "bot.lock"
LOCK_TTL = 120  # giay: lock cu hon muc nay thi coi nhu tien trinh cu da chet


def acquire_lock():
    """Chi cho phep 1 instance chay. Tra ve (True, None) neu lay duoc lock."""
    now = time.time()
    try:
        if LOCK_PATH.exists():
            try:
                pid_s, ts_s = LOCK_PATH.read_text(encoding="utf-8").strip().split("|")
                if now - float(ts_s) < LOCK_TTL:
                    return False, int(pid_s)
            except Exception:
                pass
        LOCK_PATH.write_text(f"{os.getpid()}|{now}", encoding="utf-8")
        return True, None
    except Exception:
        return True, None  # khong lock duoc thi van cho chay

# ---------------------------------------------------------------- states
(CR_PROVIDER, CR_NAME, CR_PASS, CR_DOMAIN,
 LG_PROVIDER, LG_EMAIL, LG_PASS,
 RN_LABEL, SC_KEYWORD) = range(9)

# ---------------------------------------------------------------- cache
# token ngan -> (mailbox_id, provider_msg_id, otp) de callback khong vuot 64 byte
MSG_CACHE = {}


def cache_put(mailbox_id, msg_id, otp):
    token = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    MSG_CACHE[token] = {"mailbox_id": mailbox_id, "msg_id": str(msg_id),
                        "otp": otp}
    if len(MSG_CACHE) > 800:  # chong tran bo nho
        for k in list(MSG_CACHE.keys())[:300]:
            MSG_CACHE.pop(k, None)
    return token


def cache_get(token):
    return MSG_CACHE.get(token)


# ---------------------------------------------------------------- helpers
def is_admin_user(user):
    return user is not None and user.id == ADMIN_ID


def admin_only(func):
    """Chi ADMIN_ID moi duoc chay handler. Nguoi la -> chan lich su."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat
        if not is_admin_user(user) or (chat is not None and chat.type != "private"):
            try:
                if update.callback_query:
                    await update.callback_query.answer(
                        "⛔ Bot riêng tư, chỉ phục vụ admin.", show_alert=True)
                elif update.effective_message:
                    await update.effective_message.reply_text(
                        "⛔ Bot riêng tư, chỉ phục vụ admin.")
            except Exception:
                pass
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def esc(s):
    return html.escape(str(s or ""))


def shorten(s, n):
    s = str(s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def current_settings():
    return {
        "notify_global": get_setting("notify_global", "1") == "1",
        "interval": int(get_setting(
            "poll_interval", str(POLL_INTERVAL)) or POLL_INTERVAL),
        "default_provider": get_setting(
            "default_provider", DEFAULT_PROVIDER),
        "otp_only": get_setting("otp_only", "1" if OTP_ONLY_MODE else "0") == "1",
        "short_domain": get_setting("short_domain", "0") == "1",
        "digest_mode": get_setting("digest_mode", "1") == "1",
    }


async def send_long(message, text, **kwargs):
    """Gui tin dai, tu cat nho duoi 4096 ky tu."""
    kwargs.setdefault("parse_mode", ParseMode.HTML)
    for i in range(0, len(text), 4000):
        await message.reply_text(text[i: i + 4000], **kwargs)


async def finish_with_menu(wait_msg, anchor_message, text, reply_markup=None):
    """Xoa tin 'dang xu ly...' roi gui tin moi kem menu chinh.

    (Khong the edit_text kem ReplyKeyboardMarkup - Telegram bao loi
    'Inline keyboard expected'. Cung khong duoc edit message nao dang
    mang ReplyKeyboardMarkup - Telegram bao 'Message can't be edited'.)
    """
    try:
        await wait_msg.delete()
    except Exception:
        pass
    await anchor_message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=reply_markup or main_menu())


# ---------------------------------------------------------------- format
def fmt_mailbox_line(mb):
    label = mb["label"] or mb["address"]
    marks = []
    if mb["is_active"]:
        marks.append("● đang dùng")
    if not mb["notify"]:
        marks.append("tắt TB")
    suffix = f" ({', '.join(marks)})" if marks else ""
    return f"📧 <code>{esc(mb['address'])}</code>{suffix}"


def fmt_mailbox_detail(mb):
    label = mb["label"] or "(chưa đặt tên)"
    return (
        "📧 <b>Thông tin hòm thư</b>\n"
        f"🏷️ Tên: {esc(label)}\n"
        f"📫 Mail: <code>{esc(mb['address'])}</code>\n"
        f"🌐 Provider: {esc(mb['backend'])}\n"
        f"🔔 Thông báo: {'BẬT' if mb['notify'] else 'TẮT'}\n"
        f"⭐ Hòm chính: {'CÓ' if mb['is_active'] else 'KHÔNG'}\n"
        f"📅 Tạo lúc: {esc(mb['created_at'] or '?')}\n"
        f"🔄 Check cuối: {esc(mb['last_check'] or 'chưa')}"
    )


def fmt_inbox(items):
    lines = [f"📥 <b>Hòm thư có {len(items)} mail mới nhất:</b>"]
    for i, it in enumerate(items[:10], 1):
        lines.append(
            f"{i}. 👤 {esc(shorten(it.sender, 28))}\n"
            f"   📌 {esc(shorten(it.subject or '(không tiêu đề)', 60))}")
    return "\n".join(lines)


def fmt_message_detail(mb, item, otp, candidates):
    subj = decode_mime_header(item.subject) or "(không tiêu đề)"
    subj = shorten(subj, MAX_SUBJECT_CHARS)
    body = (item.body_text or "").strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS] + "\n…(đã cắt bớt)"
    parts = [
        "📨 <b>Chi tiết mail</b>",
        f"📧 Hòm: <code>{esc(mb['address'])}</code>",
        f"👤 Từ: {esc(item.sender or '?')}",
        f"📌 Tiêu đề: {esc(subj)}",
        f"🕐 Ngày: {esc(item.date or '?')}",
    ]
    if otp:
        parts.append(f"🔑 <b>OTP: <code>{esc(otp)}</code></b>")
        others = [c for c, _s in (candidates or []) if c != otp][:3]
        if others:
            parts.append(f"🔎 Mã khác: {', '.join(esc(c) for c in others)}")
    if body:
        parts.append(f"📝 <b>Nội dung:</b>\n{esc(body)}")
    return "\n".join(parts)


def fmt_notification(mb, item, otp):
    subj = shorten(decode_mime_header(item.subject) or "(không tiêu đề)", 80)
    lines = [
        "📩 <b>Mail mới!</b>",
        f"📧 <code>{esc(mb['address'])}</code> <i>({esc(mb['backend'])})</i>",
        f"👤 Từ: {esc(shorten(item.sender, 40))}",
        f"📌 {esc(subj)}",
    ]
    if otp:
        lines.append(f"🔑 OTP: <code>{esc(otp)}</code>")
    return "\n".join(lines)


GUIDE_TEXT = """📖 <b>HƯỚNG DẪN SỬ DỤNG</b>

<b>1. Tạo mail</b>
• <b>⚡ Tạo Mail Nhanh:</b> lấy ngay 1 mail ngẫu nhiên (tự đổi provider khác nếu lỗi).
• <b>📦 Tạo nhiều mail:</b> tạo 1 lúc 5 / 10 / 15 / 20 mail.
• <b>🔐 Tạo Tài Khoản:</b> tự chọn tên mail + mật khẩu (mail.tm) để giữ mail lâu, không sợ mất.

<b>2. Nhận OTP</b>
• Bot tự quét hòm thư mỗi vài giây và <b>đẩy OTP về ngay</b> khi có mail mới.
• Bấm <b>📥 Check OTP</b> để xem thủ công bất cứ lúc nào.
• Mã OTP hiện trong khung <code>123456</code> — chạm để copy trên điện thoại.

<b>3. Quản lý nhiều hòm thư</b>
• <b>📬 Danh Sách Mail:</b> lưu nhiều hòm thư, đổi hòm chính, đổi tên, bật/tắt thông báo từng hòm, xóa.
• <b>🔄 Quét tất cả:</b> quét 1 lượt mọi hòm thư, xem tổng số mail.
• <b>🗑️ Xóa tất cả:</b> dọn sạch hòm thư (có hỏi xác nhận).
• <b>🔍 Tìm Kiếm:</b> tìm mail theo người gửi / tiêu đề.

<b>4. Tùy chỉnh</b>
• <b>⚙️ Cài Đặt:</b> bật/tắt thông báo, tốc độ quét (3s–60s), provider mặc định, chế độ chỉ gửi OTP.
• <b>🌐 Đổi Provider:</b> đổi provider cho nút Tạo Mail Nhanh.

<b>💡 Mẹo giữ mail không chết</b>
• Dùng <b>mail.tm + Tạo Tài Khoản</b> (có mật khẩu) là bền nhất.
• Nếu 1 dịch vụ không gửi OTP về (TikTok chặn domain), tạo mail ở provider khác.
• Nút <b>📊 Thống Kê</b> cho biết provider nào đang sống/chết theo thời gian thực.

<b>⭐ Domain ngắn gọn, dễ nhớ</b>
• Bật <b>⭐ Domain ngắn gọn</b> trong ⚙️ Cài Đặt: bot sẽ tạo mail đuôi ngắn
  như <code>laafd.com</code>, <code>vjuum.com</code> thay vì đuôi dài.
• Khi Tạo Tài Khoản, domain có dấu ⭐ là đuôi ngắn nhất.

<b>🔒 Chỉ mình bạn đọc được mail?</b>
• Dùng <b>mail.tm + đặt mật khẩu</b>: chỉ ai có mật khẩu mới đọc được.
• Mail <b>1secmail / Guerrilla</b>: ai biết địa chỉ đều đọc được — đừng dùng
  cho tài khoản quan trọng.
• Bản thân bot đã khóa: chỉ đúng admin mới bấm được.

⛔ Bot chỉ phục vụ đúng 1 admin, người lạ bấm vào sẽ bị chặn.
"""


# ============================================================ MENU CHINH
@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    incr_stat("starts")
    await update.effective_message.reply_text(
        "🤖 <b>MAIL OTP BOT</b> — sẵn sàng!\n"
        "Tạo mail tạm thời, nhận OTP siêu nhanh, chỉ phục vụ riêng bạn.\n"
        "Chọn chức năng bên dưới nhé 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


@admin_only
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🏠 <b>Menu chính</b> — chọn chức năng:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


@admin_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_long(update.effective_message, GUIDE_TEXT,
                    reply_markup=main_menu())


@admin_only
async def btn_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_long(update.effective_message, GUIDE_TEXT)


# ============================================================ TAO MAIL NHANH
@admin_only
async def btn_quick_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    wait = await msg.reply_text("⏳ Đang tạo mail...")
    st = current_settings()
    try:
        creds, used = await manager.create_random(
            preferred=st["default_provider"])
    except Exception as exc:
        logger.exception("quick_create failed")
        await wait.edit_text(f"❌ Tạo mail thất bại: {esc(str(exc)[:200])}")
        return
    mb_id = add_mailbox(creds)
    set_active(mb_id)
    incr_stat("mailboxes_created")
    note = manager.get(used).note
    await wait.edit_text(
        "⚡ <b>Tạo mail nhanh thành công!</b>\n"
        f"📧 <code>{esc(creds.address)}</code>\n"
        f"🌐 Provider: {esc(used)}\n"
        f"💡 {esc(note)}\n\n"
        "Mail này đã là <b>hòm chính</b>. Khi có OTP, bot sẽ đẩy về ngay.",
        parse_mode=ParseMode.HTML,
        reply_markup=after_create_kb(),
    )


# ============================================================ TAO TAI KHOAN (hoi thoai)
@admin_only
async def cr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🔐 <b>Tạo tài khoản mail</b> — chọn provider:",
        parse_mode=ParseMode.HTML,
        reply_markup=providers_kb("cr_prov"),
    )
    return CR_PROVIDER


async def cr_provider_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    backend_name = query.data.split(":", 1)[1]
    context.user_data["cr_backend"] = backend_name
    be = manager.get(backend_name)
    warn = ""
    if backend_name in ("1secmail", "guerrilla"):
        warn = ("\n\n⚠️ <b>Riêng tư:</b> ai biết địa chỉ mail này đều đọc được mail. "
                "Muốn <b>chỉ mình bạn</b> đọc được thì chọn <b>mail.tm</b> + đặt mật khẩu.")
    await query.edit_message_text(
        f"🌐 Provider: <b>{esc(be.display)}</b>{warn}\n"
        "Nhập <b>tên mail</b> bạn muốn (3–30 ký tự, chỉ chữ/số/._-):",
        parse_mode=ParseMode.HTML,
    )
    return CR_NAME


async def cr_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_message.text.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", name):
        await update.effective_message.reply_text(
            "❌ Tên không hợp lệ. Chỉ dùng chữ/số/._- , dài 3–30 ký tự.\n"
            "Nhập lại tên khác:")
        return CR_NAME
    context.user_data["cr_name"] = name.lower()
    backend_name = context.user_data["cr_backend"]
    be = manager.get(backend_name)
    if be.supports_password:
        await update.effective_message.reply_text(
            "🔑 Nhập <b>mật khẩu</b> cho hòm thư (tối thiểu 6 ký tự):",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_kb(),
        )
        return CR_PASS
    return await cr_ask_domain(update, context)


async def cr_pass_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pw = update.effective_message.text.strip()
    if len(pw) < 6:
        await update.effective_message.reply_text(
            "❌ Mật khẩu phải từ 6 ký tự trở lên. Nhập lại:")
        return CR_PASS
    context.user_data["cr_pass"] = pw
    return await cr_ask_domain(update, context)


async def cr_ask_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backend_name = context.user_data["cr_backend"]
    be = manager.get(backend_name)
    try:
        domains = await be.domains()
    except Exception as exc:
        logger.exception("domains failed")
        await update.effective_message.reply_text(
            f"❌ Không lấy được danh sách domain: {esc(str(exc)[:150])}",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
        return ConversationHandler.END
    if not domains:
        # provider khong cho chon domain (guerrilla) -> tao luon
        return await cr_do_create(update, context, domain="")
    items = []
    for d in pretty_first(domains):
        if d in PRETTY_DOMAINS:
            items.append((d, f"💎 {d}"))
        elif backend_name == "1secmail" and len(d) <= 11:
            items.append((d, f"⭐ {d}"))
        else:
            items.append((d, d))
    await update.effective_message.reply_text(
        "🌍 Chọn <b>domain</b> cho mail:\n"
        "<i>💎 = đuôi đẹp, ⭐ = đuôi ngắn dễ nhớ</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=domains_kb(items),
    )
    return CR_DOMAIN


async def cr_domain_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    domain = query.data.split(":", 1)[1]
    return await cr_do_create(update, context, domain=domain)


async def cr_do_create(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       domain):
    backend_name = context.user_data["cr_backend"]
    name = context.user_data["cr_name"]
    pw = context.user_data.get("cr_pass", "")
    be = manager.get(backend_name)
    msg = update.effective_message
    wait_msg = None
    if update.callback_query:
        wait_msg = await update.callback_query.message.reply_text("⏳ Đang tạo...")
        msg = wait_msg
    else:
        wait_msg = await msg.reply_text("⏳ Đang tạo...")
        msg = wait_msg
    try:
        creds = await be.create_account(name, pw, domain)
    except BackendError as exc:
        await wait_msg.edit_text(
            f"❌ {esc(str(exc))}\nNhập lại <b>tên mail</b> khác:",
            parse_mode=ParseMode.HTML)
        return CR_NAME
    except Exception as exc:
        logger.exception("create_account failed")
        await wait_msg.edit_text(
            f"❌ Lỗi tạo tài khoản: {esc(str(exc)[:200])}",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    mb_id = add_mailbox(creds)
    set_active(mb_id)
    incr_stat("mailboxes_created")
    extra = f"🔑 Mật khẩu: <code>{esc(pw)}</code>\n" if pw else ""
    private_note = ""
    if backend_name == "mail.tm" and pw:
        private_note = "\n🔒 Hòm này có mật khẩu — <b>chỉ mình bạn</b> đọc được mail."
    await finish_with_menu(
        wait_msg, update.effective_message,
        "✅ <b>Tạo tài khoản thành công!</b>\n"
        f"📧 <code>{esc(creds.address)}</code>\n"
        f"{extra}"
        f"🌐 Provider: {esc(backend_name)}\n"
        f"{private_note}\n"
        "Đã đặt làm <b>hòm chính</b>.",
    )
    context.user_data.pop("cr_backend", None)
    context.user_data.pop("cr_name", None)
    context.user_data.pop("cr_pass", None)
    return ConversationHandler.END


# ============================================================ DANG NHAP (hoi thoai)
@admin_only
async def lg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🔑 <b>Đăng nhập hòm thư có sẵn</b> — chọn provider:",
        parse_mode=ParseMode.HTML,
        reply_markup=providers_kb("lg_prov", only=["mail.tm", "1secmail"]),
    )
    return LG_PROVIDER


async def lg_provider_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    backend_name = query.data.split(":", 1)[1]
    context.user_data["lg_backend"] = backend_name
    await query.edit_message_text(
        "Nhập <b>địa chỉ mail</b> cần đăng nhập:",
        parse_mode=ParseMode.HTML,
    )
    return LG_EMAIL


async def lg_email_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.effective_message.text.strip().lower()
    if "@" not in email:
        await update.effective_message.reply_text("❌ Mail không hợp lệ, nhập lại:")
        return LG_EMAIL
    context.user_data["lg_email"] = email
    backend_name = context.user_data["lg_backend"]
    if manager.get(backend_name).supports_password:
        await update.effective_message.reply_text(
            "🔑 Nhập <b>mật khẩu</b> của hòm thư:",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_kb(),
        )
        return LG_PASS
    return await lg_do_login(update, context, password="")


async def lg_pass_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pw = update.effective_message.text.strip()
    return await lg_do_login(update, context, password=pw)


async def lg_do_login(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      password):
    backend_name = context.user_data["lg_backend"]
    email = context.user_data["lg_email"]
    be = manager.get(backend_name)
    wait = await update.effective_message.reply_text("⏳ Đang đăng nhập...")
    try:
        creds = await be.login(email, password)
    except BackendError as exc:
        await wait.edit_text(f"❌ {esc(str(exc))}", parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    except Exception as exc:
        logger.exception("login failed")
        await wait.edit_text(f"❌ Lỗi đăng nhập: {esc(str(exc)[:200])}",
                             parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    old = get_mailbox_by_address(creds.address)
    if old:
        update_mailbox_token(old["id"], creds.token)
        update_mailbox_extra(old["id"], creds.extra)
        set_active(old["id"])
        mb_id = old["id"]
    else:
        mb_id = add_mailbox(creds)
        set_active(mb_id)
    await finish_with_menu(
        wait, update.effective_message,
        "✅ <b>Đăng nhập thành công!</b>\n"
        f"📧 <code>{esc(creds.address)}</code>\n"
        f"🌐 Provider: {esc(backend_name)}",
    )
    context.user_data.pop("lg_backend", None)
    context.user_data.pop("lg_email", None)
    return ConversationHandler.END


# ============================================================ HUY HOI THOAI
@admin_only
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for k in ("cr_backend", "cr_name", "cr_pass", "lg_backend", "lg_email"):
        context.user_data.pop(k, None)
    target = update.callback_query or update
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "❌ Đã hủy thao tác.", reply_markup=main_menu())
    else:
        await update.effective_message.reply_text(
            "❌ Đã hủy thao tác.", reply_markup=main_menu())
    return ConversationHandler.END


@admin_only
async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.effective_message.reply_text(
        f"🆔 ID của bạn: <code>{u.id}</code>\n"
        f"👤 Username: @{esc(u.username or '?')}",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🤔 Mình chưa hiểu. Bấm <b>🏠 Menu</b> hoặc /menu để xem chức năng nhé.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================ CHECK / INBOX
async def fetch_items(creds, mb_id):
    """Lay danh sach mail; tu relogin mail.tm khi token het han."""
    backend = manager.get(creds.backend)
    try:
        items = await backend.list_messages(creds)
    except AuthError:
        if creds.backend == "mail.tm":
            await backend.relogin(creds)
            update_mailbox_token(mb_id, creds.token)
            update_mailbox_extra(mb_id, creds.extra)
            items = await backend.list_messages(creds)
        else:
            raise
    update_mailbox_extra(mb_id, creds.extra)
    update_last_check(mb_id)
    return items


async def show_inbox_list(message, mb, items):
    if not items:
        await message.reply_text(
            f"📭 Hòm thư <code>{esc(mb['address'])}</code> đang trống.\n"
            "Bấm 🔄 Refresh để quét lại.",
            parse_mode=ParseMode.HTML,
            reply_markup=inbox_kb([]),
        )
        return
    tokens = []
    for it in items[:10]:
        otp, _c = extract_best_otp(
            (it.subject or "") + "\n" + (it.preview or ""))
        tok = cache_put(mb["id"], it.msg_id, otp)
        label = (f"{shorten(it.sender, 22)} — "
                 f"{shorten(it.subject or '(không tiêu đề)', 32)}")
        tokens.append((tok, label))
    text = (f"📥 <b>{esc(mb['address'])}</b> "
            f"<i>({esc(mb['backend'])})</i>\n" + fmt_inbox(items))
    await message.reply_text(text, parse_mode=ParseMode.HTML,
                             reply_markup=inbox_kb(tokens))


def get_default_mailbox():
    mb = get_active_mailbox()
    if mb:
        return mb
    boxes = list_mailboxes()
    return boxes[0] if boxes else None


@admin_only
async def btn_check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    mb = get_default_mailbox()
    if not mb:
        await msg.reply_text("📭 Bạn chưa có hòm thư nào. Bấm <b>⚡ Tạo Mail Nhanh</b> trước nhé.",
                             parse_mode=ParseMode.HTML)
        return
    wait = await msg.reply_text("⏳ Đang quét hòm thư...")
    try:
        items = await fetch_items(creds_from_row(mb), mb["id"])
    except Exception as exc:
        logger.exception("check_now failed")
        await wait.edit_text(f"❌ Không quét được: {esc(str(exc)[:200])}")
        return
    await wait.delete()
    await show_inbox_list(msg, mb, items)


@admin_only
async def btn_my_mailbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mb = get_default_mailbox()
    if not mb:
        await update.effective_message.reply_text(
            "📭 Bạn chưa có hòm thư nào. Bấm <b>⚡ Tạo Mail Nhanh</b> trước nhé.",
            parse_mode=ParseMode.HTML)
        return
    await update.effective_message.reply_text(
        fmt_mailbox_detail(mb), parse_mode=ParseMode.HTML,
        reply_markup=mailbox_detail_kb(mb["id"], mb["is_active"], mb["notify"]))


@admin_only
async def btn_mailbox_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    boxes = list_mailboxes()
    if not boxes:
        await update.effective_message.reply_text(
            "📭 Chưa có hòm thư nào. Bấm <b>⚡ Tạo Mail Nhanh</b> để tạo.",
            parse_mode=ParseMode.HTML)
        return
    active = get_active_mailbox()
    active_id = active["id"] if active else -1
    lines = ["📬 <b>Danh sách hòm thư</b> — bấm vào từng hòm để quản lý:"]
    for b in boxes:
        lines.append(fmt_mailbox_line(b))
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=mailbox_list_kb(boxes, active_id))


# ============================================================ TIM KIEM (hoi thoai)
@admin_only
async def sc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    boxes = list_mailboxes()
    if not boxes:
        await update.effective_message.reply_text("📭 Chưa có hòm thư nào để tìm.")
        return ConversationHandler.END
    await update.effective_message.reply_text(
        "🔍 Nhập <b>từ khóa</b> cần tìm (người gửi hoặc tiêu đề):",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_kb(),
    )
    return SC_KEYWORD


async def sc_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kw = update.effective_message.text.strip().lower()
    # LUU Y: khong gan ReplyKeyboardMarkup cho tin wait, vi sau do can
    # edit_text no -> Telegram se bao "Message can't be edited".
    wait = await update.effective_message.reply_text("⏳ Đang tìm...")
    results = []
    for mb in list_mailboxes():
        try:
            items = await fetch_items(creds_from_row(mb), mb["id"])
        except Exception:
            continue
        for it in items[:25]:
            hay = f"{it.sender} {it.subject}".lower()
            if kw in hay:
                otp, _c = extract_best_otp(
                    (it.subject or "") + "\n" + (it.preview or ""))
                tok = cache_put(mb["id"], it.msg_id, otp)
                results.append((mb, it, tok))
                if len(results) >= 15:
                    break
        if len(results) >= 15:
            break
    if not results:
        await finish_with_menu(
            wait, update.effective_message,
            f"🔍 Không tìm thấy mail nào chứa <b>{esc(kw)}</b>.")
        return ConversationHandler.END
    lines = [f"🔍 Tìm thấy <b>{len(results)}</b> mail chứa <b>{esc(kw)}</b>:"]
    rows = []
    for mb, it, tok in results:
        lines.append(f"• <code>{esc(mb['address'])}</code> — "
                     f"{esc(shorten(it.subject or '(không tiêu đề)', 50))}")
        rows.append([InlineKeyboardButton(
            f"✉️ {shorten(it.subject or '(không tiêu đề)', 34)}",
            callback_data=f"view:{tok}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    await finish_with_menu(wait, update.effective_message, "\n".join(lines),
                           reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END


# ============================================================ DOI TEN (hoi thoai)
async def rn_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin_user(query.from_user):
        await query.answer("⛔ Bot riêng tư.", show_alert=True)
        return ConversationHandler.END
    mb_id = int(query.data.split(":")[1])
    mb = get_mailbox(mb_id)
    if not mb:
        await query.answer("Hòm thư không còn tồn tại.", show_alert=True)
        return ConversationHandler.END
    context.user_data["rn_id"] = mb_id
    await query.answer()
    await query.message.reply_text(
        f"✏️ Nhập <b>tên gợi nhớ</b> cho hòm <code>{esc(mb['address'])}</code>:",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_kb(),
    )
    return RN_LABEL


async def rn_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = update.effective_message.text.strip()[:40]
    mb_id = context.user_data.pop("rn_id", None)
    if mb_id:
        rename_mailbox(mb_id, label)
    await update.effective_message.reply_text(
        f"✅ Đã đặt tên: <b>{esc(label)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


# ============================================================ CAI DAT / THONG KE / KHAC
def settings_text():
    st = current_settings()
    return (
        "⚙️ <b>Cài đặt</b>\n"
        f"🔔 Thông báo tự động: <b>{'BẬT' if st['notify_global'] else 'TẮT'}</b>\n"
        f"⏱️ Quét mỗi: <b>{st['interval']} giây</b>\n"
        f"🌐 Provider mặc định: <b>{esc(st['default_provider'])}</b>\n"
        f"⚡ Chế độ chỉ gửi OTP: <b>{'BẬT' if st['otp_only'] else 'TẮT'}</b>\n"
        f"⭐ Ưu tiên domain ngắn: <b>{'BẬT' if st['short_domain'] else 'TẮT'}</b>"
    )


@admin_only
async def btn_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = current_settings()
    await update.effective_message.reply_text(
        settings_text(), parse_mode=ParseMode.HTML,
        reply_markup=settings_kb(st["notify_global"], st["interval"],
                                    st["default_provider"], st["otp_only"],
                                    st["short_domain"], st["digest_mode"]))


@admin_only
async def btn_change_provider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = current_settings()
    await update.effective_message.reply_text(
        f"🌐 Provider mặc định hiện tại: <b>{esc(st['default_provider'])}</b>\n"
        "Chọn provider cho nút <b>⚡ Tạo Mail Nhanh</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=providers_kb("setp"),
    )


def format_uptime(sec):
    sec = int(sec)
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


@admin_only
async def btn_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await update.effective_message.reply_text("⏳ Đang kiểm tra...")
    text = await build_stats_text()
    await wait.edit_text(text, parse_mode=ParseMode.HTML)


async def build_stats_text():
    stats = get_all_stats()
    boxes = list_mailboxes()
    health = await manager.health_all()
    lines = [
        "📊 <b>THỐNG KÊ</b>",
        f"⏱️ Uptime: {format_uptime(time.time() - START_TIME)}",
        f"📧 Tổng hòm thư: <b>{len(boxes)}</b>",
        f"📨 Mail đã nhận: <b>{stats.get('messages_received', 0)}</b>",
        f"🔑 OTP đã tách: <b>{stats.get('otps_found', 0)}</b>",
        "",
        "🌐 <b>Trạng thái provider:</b>",
    ]
    for name in manager.names():
        ok, ms, note = health.get(name, (False, 0, "?"))
        icon = "🟢" if ok else "🔴"
        lines.append(
            f"{icon} {esc(manager.display_name(name))}: {ms}ms <i>{esc(note)}</i>")
    return "\n".join(lines)


@admin_only
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await update.effective_message.reply_text("⏳ Đang ping provider...")
    health = await manager.health_all()
    lines = ["🏓 <b>Ping provider:</b>"]
    for name in manager.names():
        ok, ms, note = health.get(name, (False, 0, "?"))
        icon = "🟢" if ok else "🔴"
        lines.append(
            f"{icon} {esc(manager.display_name(name))}: {ms}ms <i>{esc(note)}</i>")
    await wait.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


@admin_only
async def btn_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    boxes = list_mailboxes()
    if not boxes:
        await update.effective_message.reply_text("📭 Chưa có hòm thư nào để xuất.")
        return
    lines = ["# Danh sach hom thu Mail OTP Bot",
             f"# Xuat luc: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for b in boxes:
        lines.append(
            f"{b['address']} | {b['backend']} | ten={b['label'] or '-'} | "
            f"active={b['is_active']} | notify={b['notify']} | tao={b['created_at']}")
    path = Path(DATA_DIR) / \
        f"export_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    await update.effective_message.reply_document(
        document=open(path, "rb"),
        filename=path.name,
        caption=f"📤 Đã xuất <b>{len(boxes)}</b> hòm thư.",
        parse_mode=ParseMode.HTML,
    )
    incr_stat("exports")


# ============================================================ TAO HANG LOAT / BACKUP
@admin_only
async def btn_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📦 <b>Tạo nhiều mail cùng lúc</b> — chọn số lượng:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("5 mail", callback_data="batch:5"),
            InlineKeyboardButton("10 mail", callback_data="batch:10"),
        ], [
            InlineKeyboardButton("15 mail", callback_data="batch:15"),
            InlineKeyboardButton("20 mail", callback_data="batch:20"),
        ]]))


async def do_batch_create(message, n):
    st = current_settings()
    wait = await message.reply_text(f"⏳ Đang tạo {n} mail...")
    created, failed = [], 0
    for _ in range(n):
        try:
            creds, used = await quick_create_creds(st)
            mid = add_mailbox(creds)
            if not get_active_mailbox():
                set_active(mid)
            incr_stat("mailboxes_created")
            created.append((creds.address, used))
        except Exception:
            failed += 1
            logger.exception("batch create item failed")
    if not created:
        await wait.edit_text("❌ Tạo mail thất bại ở tất cả provider.")
        return
    lines = [f"⚡ <b>Đã tạo {len(created)}/{n} mail:</b>"]
    for addr, used in created:
        lines.append(f"• <code>{esc(addr)}</code> <i>({esc(used)})</i>")
    if failed:
        lines.append(f"⚠️ {failed} mail bị lỗi.")
    lines.append("\nHòm đầu tiên đã đặt làm <b>hòm chính</b>.")
    await wait.edit_text("\n".join(lines), parse_mode=ParseMode.HTML,
                         reply_markup=after_create_kb())


async def send_backup(message):
    path = Path(DB_PATH)
    if not path.exists():
        await message.reply_text("📭 Chưa có dữ liệu để sao lưu.")
        return
    fname = f"mailbot_backup_{time.strftime('%Y%m%d_%H%M%S')}.db"
    with open(path, "rb") as f:
        await message.reply_document(
            document=f, filename=fname,
            caption="💾 Backup dữ liệu bot (hòm thư + cài đặt).\n"
                    "Giữ file này cẩn thận, đừng gửi cho ai.")
    incr_stat("backups")


@admin_only
async def btn_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_backup(update.effective_message)


@admin_only
async def cmd_restore_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "♻️ <b>Khôi phục dữ liệu</b>\n\n"
        "Gửi <b>file .db</b> backup vào chat này (kéo-thả file), "
        "bot sẽ thay thế dữ liệu hiện tại bằng file đó.\n"
        "Dùng khi deploy lại mà dữ liệu bị mất.",
        parse_mode=ParseMode.HTML)


@admin_only
async def restore_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin gui file .db -> khoi phuc du lieu bot."""
    msg = update.effective_message
    doc = msg.document if msg else None
    if not doc or not (doc.file_name or "").lower().endswith(".db"):
        return
    tmp = Path(DATA_DIR) / "_restore_tmp.db"
    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(tmp)
    except Exception as exc:
        await msg.reply_text(f"❌ Không tải được file: {exc}")
        return
    try:
        con = sqlite3.connect(tmp)
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except Exception:
        tmp.unlink(missing_ok=True)
        await msg.reply_text("❌ File không phải database SQLite hợp lệ.")
        return
    if not ({"mailboxes", "settings"} & tables):
        tmp.unlink(missing_ok=True)
        await msg.reply_text(
            "❌ File DB này không phải dữ liệu của bot.")
        return
    try:
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
        import shutil as _sh
        _sh.copy(tmp, Path(DB_PATH))
        init_db()
        n = len(list_mailboxes())
    except Exception as exc:
        await msg.reply_text(f"❌ Khôi phục lỗi: {exc}")
        return
    finally:
        tmp.unlink(missing_ok=True)
    await msg.reply_text(
        f"✅ Đã khôi phục dữ liệu ({n} hòm thư). Bot chạy tiếp bình thường.")


# ============================================================ LICH SU OTP
@admin_only
async def btn_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_otp_history(15)
    if not rows:
        await update.effective_message.reply_text(
            "🕘 Chưa có OTP nào được ghi lại.\n"
            "OTP sẽ tự lưu vào đây mỗi khi bot đẩy thông báo mail mới.")
        return
    lines = ["🕘 <b>Lịch sử OTP gần nhất:</b>"]
    for r in rows:
        lines.append(
            f"🔑 <code>{esc(r['otp'])}</code> — "
            f"{esc(shorten(r['address'], 26))}\n"
            f"   👤 {esc(shorten(r['sender'], 30))} · {esc(r['created_at'])}")
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗑️ Xóa lịch sử",
                                   callback_data="hist:clear")]]))


# ============================================================ CALLBACK DISPATCHER
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin_user(query.from_user):
        await query.answer("⛔ Bot riêng tư, chỉ phục vụ admin.", show_alert=True)
        return
    data = query.data or ""

    if data == "noop":
        await query.answer()
        return

    if data == "menu":
        await query.answer()
        await query.message.reply_text("🏠 <b>Menu chính</b>:",
                                       parse_mode=ParseMode.HTML,
                                       reply_markup=main_menu())
        return

    if data == "quick_create":
        await query.answer("⏳ Đang tạo mail...")
        await do_quick_create(query.message)
        return

    if data == "check_now":
        await query.answer("⏳ Đang quét...")
        mb = get_default_mailbox()
        if not mb:
            await query.message.reply_text("📭 Chưa có hòm thư nào.")
            return
        try:
            items = await fetch_items(creds_from_row(mb), mb["id"])
        except Exception as exc:
            await query.message.reply_text(
                f"❌ Không quét được: {esc(str(exc)[:200])}",
                parse_mode=ParseMode.HTML)
            return
        await show_inbox_list(query.message, mb, items)
        return

    if data.startswith("view:"):
        await cb_view(query, data[5:])
        return

    if data.startswith("otp:"):
        await cb_otp(query, data[4:])
        return

    if data == "mb_list":
        await query.answer()
        boxes = list_mailboxes()
        active = get_active_mailbox()
        active_id = active["id"] if active else -1
        lines = ["📬 <b>Danh sách hòm thư:</b>"]
        for b in boxes:
            lines.append(fmt_mailbox_line(b))
        try:
            await query.edit_message_text(
                "\n".join(lines), parse_mode=ParseMode.HTML,
                reply_markup=mailbox_list_kb(boxes, active_id))
        except Exception:
            await query.message.reply_text(
                "\n".join(lines), parse_mode=ParseMode.HTML,
                reply_markup=mailbox_list_kb(boxes, active_id))
        return

    if data.startswith("mb_pass:"):
        mb_id = int(data.split(":")[1])
        mb = get_mailbox(mb_id)
        if not mb:
            await query.answer("Hòm thư không còn tồn tại.", show_alert=True)
            return
        await query.answer()
        pw = mb.get("password")
        if pw:
            await query.message.reply_text(
                f"🔑 Mật khẩu hòm <code>{esc(mb['address'])}</code>:\n"
                f"<code>{esc(pw)}</code>",
                parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text(
                f"Hòm <code>{esc(mb['address'])}</code> không dùng mật khẩu "
                f"(provider {esc(mb['backend'])}).",
                parse_mode=ParseMode.HTML)
        return

    if data.startswith("batch:"):
        try:
            n = int(data.split(":")[1])
        except ValueError:
            n = 5
        n = max(1, min(20, n))
        await query.answer(f"⏳ Đang tạo {n} mail...")
        await do_batch_create(query.message, n)
        return

    if data == "hist:clear":
        clear_otp_history()
        await query.answer("Đã xóa lịch sử OTP.")
        await query.edit_message_text("🕘 Lịch sử OTP đã được xóa sạch.",
                                      parse_mode=ParseMode.HTML)
        return

    if data == "mb_scanall":
        await query.answer("⏳ Đang quét tất cả hòm thư...")
        boxes = list_mailboxes()
        if not boxes:
            await query.message.reply_text("📭 Chưa có hòm thư nào.")
            return
        lines = ["🔄 <b>Kết quả quét tất cả hòm thư:</b>"]
        total = 0
        for mb in boxes:
            try:
                items = await fetch_items(creds_from_row(mb), mb["id"])
            except Exception as exc:
                lines.append(
                    f"🔴 <code>{esc(mb['address'])}</code> — "
                    f"lỗi: {esc(str(exc)[:60])}")
                continue
            total += len(items)
            newest = (shorten(items[0].subject or "(không tiêu đề)", 40)
                      if items else "trống")
            lines.append(
                f"📧 <code>{esc(mb['address'])}</code>: "
                f"<b>{len(items)}</b> mail — {esc(newest)}")
        lines.append(
            f"\n📊 Tổng: <b>{total}</b> mail trong {len(boxes)} hòm thư.")
        await send_long(query.message, "\n".join(lines))
        return

    if data == "mb_delall":
        boxes = list_mailboxes()
        if not boxes:
            await query.answer("Không có hòm thư nào.", show_alert=True)
            return
        await query.edit_message_text(
            f"⚠️ Xóa <b>{len(boxes)}</b> hòm thư? Không thể hoàn tác!",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_delete_all_kb())
        return

    if data == "mb_delall_yes":
        delete_all_mailboxes()
        await query.answer("Đã xóa tất cả hòm thư.")
        await query.edit_message_text("🗑️ Đã xóa toàn bộ hòm thư.",
                                      parse_mode=ParseMode.HTML)
        return

    if data.startswith("mb_del_yes:"):
        mb_id = int(data.split(":")[1])
        delete_mailbox(mb_id)
        await query.answer("Đã xóa hòm thư.")
        boxes = list_mailboxes()
        active = get_active_mailbox()
        active_id = active["id"] if active else -1
        await query.edit_message_text(
            "🗑️ Đã xóa hòm thư.\n📬 <b>Danh sách hòm thư:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=mailbox_list_kb(boxes, active_id))
        return

    if data.startswith("mb_del:"):
        mb_id = int(data.split(":")[1])
        mb = get_mailbox(mb_id)
        if not mb:
            await query.answer("Hòm thư không còn tồn tại.", show_alert=True)
            return
        await query.edit_message_text(
            f"⚠️ Xóa hòm <code>{esc(mb['address'])}</code>?\n"
            "Mail trong hòm này sẽ không đọc được nữa.",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_delete_kb(mb_id))
        return

    if data.startswith("mb_active:"):
        mb_id = int(data.split(":")[1])
        set_active(mb_id)
        await query.answer("✅ Đã đặt làm hòm chính.")
        mb = get_mailbox(mb_id)
        await query.edit_message_text(
            fmt_mailbox_detail(mb), parse_mode=ParseMode.HTML,
            reply_markup=mailbox_detail_kb(mb_id, True, mb["notify"]))
        return

    if data.startswith("mb_notify:"):
        mb_id = int(data.split(":")[1])
        mb = get_mailbox(mb_id)
        if not mb:
            await query.answer("Hòm thư không còn tồn tại.", show_alert=True)
            return
        set_notify(mb_id, not mb["notify"])
        mb = get_mailbox(mb_id)
        await query.answer(
            f"Thông báo hòm này: {'BẬT' if mb['notify'] else 'TẮT'}")
        # neu dang xem detail thi ve lai detail, neu tu tin nhan notify thi xoa nut
        try:
            await query.edit_message_reply_markup(
                reply_markup=mailbox_detail_kb(
                    mb_id, mb["is_active"], mb["notify"]))
        except Exception:
            pass
        return

    if data.startswith("mb_check:"):
        mb_id = int(data.split(":")[1])
        mb = get_mailbox(mb_id)
        if not mb:
            await query.answer("Hòm thư không còn tồn tại.", show_alert=True)
            return
        await query.answer("⏳ Đang quét...")
        try:
            items = await fetch_items(creds_from_row(mb), mb_id)
        except Exception as exc:
            await query.message.reply_text(
                f"❌ Không quét được: {esc(str(exc)[:200])}",
                parse_mode=ParseMode.HTML)
            return
        await show_inbox_list(query.message, mb, items)
        return

    if data.startswith("mb:"):
        mb_id = int(data.split(":")[1])
        mb = get_mailbox(mb_id)
        if not mb:
            await query.answer("Hòm thư không còn tồn tại.", show_alert=True)
            return
        await query.edit_message_text(
            fmt_mailbox_detail(mb), parse_mode=ParseMode.HTML,
            reply_markup=mailbox_detail_kb(mb_id, mb["is_active"],
                                             mb["notify"]))
        return

    if data.startswith("setp:"):
        backend_name = data.split(":", 1)[1]
        if backend_name in manager.names():
            set_setting("default_provider", backend_name)
            await query.answer(f"Đã chọn {manager.display_name(backend_name)}")
            await query.edit_message_text(
                f"✅ Provider mặc định cho <b>⚡ Tạo Mail Nhanh</b>: "
                f"<b>{esc(manager.display_name(backend_name))}</b>",
                parse_mode=ParseMode.HTML)
        return

    if data.startswith("set:"):
        await cb_settings(query, data[4:])
        return

    await query.answer()


async def cb_view(query, token):
    info = cache_get(token)
    if not info:
        await query.answer("Tin đã hết hạn, bấm 📥 Check OTP để tải lại.",
                           show_alert=True)
        return
    await query.answer("⏳ Đang tải...")
    mb = get_mailbox(info["mailbox_id"])
    if not mb:
        await query.message.reply_text("❌ Hòm thư không còn tồn tại.")
        return
    creds = creds_from_row(mb)
    backend = manager.get(creds.backend)
    try:
        item = await backend.read_message(creds, info["msg_id"])
    except AuthError:
        if creds.backend == "mail.tm":
            await backend.relogin(creds)
            update_mailbox_token(mb["id"], creds.token)
            item = await backend.read_message(creds, info["msg_id"])
        else:
            raise
    except Exception as exc:
        logger.exception("read_message failed")
        await query.message.reply_text(
            f"❌ Không đọc được mail: {esc(str(exc)[:200])}",
            parse_mode=ParseMode.HTML)
        return
    otp = info.get("otp")
    full = (item.subject or "") + "\n" + (item.body_text or "")
    _best, cands = extract_best_otp(full)
    if not otp:
        otp = _best
    text = fmt_message_detail(mb, item, otp, cands)
    await send_long(query.message, text,
                    reply_markup=message_kb(token, bool(otp), mb["id"]))


async def cb_otp(query, token):
    info = cache_get(token)
    otp = (info or {}).get("otp")
    if not otp:
        await query.answer("Không tách được OTP từ mail này.", show_alert=True)
        return
    await query.answer()
    await query.message.reply_text(
        f"🔑 OTP của bạn (chạm để copy):\n<code>{esc(otp)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cb_settings(query, action):
    st = current_settings()
    if action == "backup":
        await query.answer("⏳ Đang chuẩn bị file...")
        await send_backup(query.message)
    elif action == "notify":
        set_setting("notify_global",
                            "0" if st["notify_global"] else "1")
        await query.answer("Đã đổi chế độ thông báo.")
    elif action == "otponly":
        set_setting("otp_only", "0" if st["otp_only"] else "1")
        await query.answer("Đã đổi chế độ chỉ gửi OTP.")
    elif action == "digest":
        set_setting("digest_mode", "0" if st["digest_mode"] else "1")
        await query.answer("Đã đổi chế độ gom thông báo.")
    elif action == "shortdomain":
        set_setting("short_domain", "0" if st["short_domain"] else "1")
        await query.answer("Đã đổi chế độ domain ngắn gọn.")
    elif action == "testnotify":
        await query.answer("Đã gửi tin test.")
        await query.message.reply_text(
            "🔔 <b>Test thông báo thành công!</b>\n"
            "Bot quét mail & đẩy OTP bình thường ✅",
            parse_mode=ParseMode.HTML)
    elif action.startswith("interval:"):
        try:
            sec = int(action.split(":")[1])
        except ValueError:
            sec = POLL_INTERVAL
        sec = max(POLL_MIN_INTERVAL,
                  min(POLL_MAX_INTERVAL, sec))
        set_setting("poll_interval", str(sec))
        await query.answer(f"Đã đặt quét mỗi {sec}s.")
    elif action.startswith("provider:"):
        name = action.split(":", 1)[1]
        if name in manager.names():
            set_setting("default_provider", name)
            await query.answer(f"Đã chọn {manager.display_name(name)}.")
    st = current_settings()
    await query.edit_message_text(
        settings_text(), parse_mode=ParseMode.HTML,
        reply_markup=settings_kb(st["notify_global"], st["interval"],
                                    st["default_provider"], st["otp_only"],
                                    st["short_domain"], st["digest_mode"]))


async def quick_create_creds(st):
    """Tao mail nhanh. Neu bat 'domain ngan' thi dung 1secmail + domain ngan nhat."""
    if st["short_domain"]:
        try:
            be = manager.get("1secmail")
            domains = await be.domains()
            uname = "".join(random.choices(
                string.ascii_lowercase + string.digits, k=10))
            creds = await be.create_account(uname, "", domains[0])
            return creds, "1secmail"
        except Exception as exc:
            logger.warning("short-domain quick create loi, fallback: %s", exc)
    return await manager.create_random(preferred=st["default_provider"])


async def do_quick_create(message):
    st = current_settings()
    try:
        creds, used = await quick_create_creds(st)
    except Exception as exc:
        logger.exception("quick_create failed")
        await message.reply_text(
            f"❌ Tạo mail thất bại: {esc(str(exc)[:200])}",
            parse_mode=ParseMode.HTML)
        return
    mb_id = add_mailbox(creds)
    set_active(mb_id)
    incr_stat("mailboxes_created")
    await message.reply_text(
        "⚡ <b>Tạo mail nhanh thành công!</b>\n"
        f"📧 <code>{esc(creds.address)}</code>\n"
        f"🌐 Provider: {esc(used)}\n\n"
        "Đã đặt làm <b>hòm chính</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=after_create_kb(),
    )


# ============================================================ VONG QUET NEN
async def poll_one_mailbox(app, mb, st):
    """Quet 1 hop thu — TRA VE danh sach mail moi (khong gui tin truc tiep).
    Viec gui tin do poll_loop gom lai (digest) de chong spam."""
    creds = creds_from_row(mb)
    try:
        items = await safe_list_messages(creds, mb["id"])
    except Exception as exc:
        logger.warning("poll %s (%s) loi: %s", mb["address"], mb["backend"], exc)
        return []
    new_items = [it for it in items if not is_seen(mb["id"], it.msg_id)]
    if not new_items:
        return []
    backend = manager.get(creds.backend)
    out = []
    for it in new_items:
        mark_seen(mb["id"], it.msg_id)
        incr_stat("messages_received")
        try:
            detail = await backend.read_message(creds, it.msg_id)
            full_text = (detail.subject or "") + "\n" + (detail.body_text or "")
        except Exception:
            logger.warning("read detail failed, dung preview")
            full_text = (it.subject or "") + "\n" + (it.preview or "")
        otp, _cands = extract_best_otp(full_text)
        if otp:
            incr_stat("otps_found")
            add_otp_history(mb["address"], otp, it.sender)
        tok = cache_put(mb["id"], it.msg_id, otp)
        out.append({"mb": mb, "item": it, "otp": otp, "tok": tok})
    return out


async def send_single_notification(app, e, st):
    """Gui 1 tin cho 1 mail (che do cu, khi tat digest)."""
    mb, it, otp, tok = e["mb"], e["item"], e["otp"], e["tok"]
    if st["otp_only"] and otp:
        text = (f"🔑 <code>{esc(otp)}</code>\n"
                f"📧 {esc(mb['address'])}\n"
                f"👤 {esc(shorten(it.sender, 40))}")
    else:
        text = fmt_notification(mb, it, otp)
    try:
        await app.bot.send_message(
            chat_id=ADMIN_ID, text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=message_kb(tok, bool(otp), mb["id"]))
    except Exception:
        logger.exception("gui thong bao that bai")


async def send_digest(app, collected, st):
    """Gom nhieu mail moi thanh 1 tin duy nhat — chong spam tin nhan."""
    otps = [e for e in collected if e["otp"]]
    others = [e for e in collected if not e["otp"]]
    lines = ["📬 <b>Có %d mail mới</b> (%d OTP)" % (len(collected), len(otps)),
             ""]
    for e in otps:
        lines.append(
            f"🔑 <code>{esc(e['otp'])}</code>\n"
            f"   📧 {esc(e['mb']['address'])}\n"
            f"   👤 {esc(shorten(e['item'].sender, 40))}\n")
    if others and not st["otp_only"]:
        for e in others[:5]:
            lines.append(
                f"✉️ {esc(shorten(e['item'].subject, 50))}\n"
                f"   📧 {esc(e['mb']['address'])}\n")
        if len(others) > 5:
            lines.append(f"<i>…và {len(others) - 5} mail khác</i>")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📬 Danh sách mail", callback_data="mb_list")],
    ])
    try:
        await app.bot.send_message(
            chat_id=ADMIN_ID, text="\n".join(lines),
            parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        logger.exception("gui digest that bai")


async def poll_loop(app):
    await asyncio.sleep(4)
    logger.info("poll loop started")
    while True:
        try:
            # giu lock tuoi -> instance khac biet minh van song
            try:
                LOCK_PATH.write_text(f"{os.getpid()}|{time.time()}",
                                     encoding="utf-8")
            except Exception:
                pass
            st = current_settings()
            collected = []
            if st["notify_global"]:
                for mb in list_mailboxes():
                    if not mb["notify"]:
                        continue
                    if not prov_healthy(mb["backend"]):
                        continue
                    collected += await poll_one_mailbox(app, mb, st)
                    await asyncio.sleep(0.7)
            if collected:
                # gom thanh 1 tin (digest) de khong spam tin nhan
                if st.get("digest_mode", True):
                    await send_digest(app, collected, st)
                else:
                    for e in collected:
                        await send_single_notification(app, e, st)
            await asyncio.sleep(max(POLL_MIN_INTERVAL, st["interval"]))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("poll_loop error")
            await asyncio.sleep(10)


# ============================================================ ERROR / MAIN
# Loi kieu nay chi log, KHONG spam tin nhan ve Telegram cho admin
_SUPPRESSED_ERRORS = (
    "Conflict", "getUpdates",               # 2 instance cung chay
    "Message can't be edited",              # edit message mang reply keyboard
    "message is not modified",              # bam nut 2 lan
    "message to edit not found",
    "query is too old",
)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    err_text = str(context.error)
    logger.error("Unhandled error: %s", context.error,
                 exc_info=context.error)
    if any(s in err_text for s in _SUPPRESSED_ERRORS):
        logger.warning("Loi thuoc dien suppress (%s) - da bo qua thong bao.",
                       err_text[:80])
        return
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"⚠️ <b>Lỗi bot:</b> <code>{esc(str(context.error)[:300])}</code>",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    traceback.print_exc()


def build_conversations():
    create_conv = ConversationHandler(
        entry_points=[MessageHandler(
            filters.Regex(r"^🔐 Tạo Tài Khoản$") & filters.ChatType.PRIVATE,
            cr_start)],
        states={
            CR_PROVIDER: [CallbackQueryHandler(cr_provider_chosen,
                                               pattern=r"^cr_prov:")],
            CR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                     cr_name_received)],
            CR_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                     cr_pass_received)],
            CR_DOMAIN: [CallbackQueryHandler(cr_domain_chosen,
                                             pattern=r"^cr_dom:")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel),
                   MessageHandler(filters.Regex(r"^❌ Hủy$"), cmd_cancel),
                   CallbackQueryHandler(cmd_cancel, pattern=r"^noop$")],
    )
    login_conv = ConversationHandler(
        entry_points=[MessageHandler(
            filters.Regex(r"^🔑 Đăng Nhập$") & filters.ChatType.PRIVATE,
            lg_start)],
        states={
            LG_PROVIDER: [CallbackQueryHandler(lg_provider_chosen,
                                                pattern=r"^lg_prov:")],
            LG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                      lg_email_received)],
            LG_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                      lg_pass_received)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel),
                   MessageHandler(filters.Regex(r"^❌ Hủy$"), cmd_cancel)],
    )
    rename_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rn_start, pattern=r"^mb_rename:\d+$")],
        states={
            RN_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, rn_done)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel),
                   MessageHandler(filters.Regex(r"^❌ Hủy$"), cmd_cancel)],
    )
    search_conv = ConversationHandler(
        entry_points=[MessageHandler(
            filters.Regex(r"^🔍 Tìm Kiếm$") & filters.ChatType.PRIVATE,
            sc_start)],
        states={
            SC_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, sc_do)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel),
                   MessageHandler(filters.Regex(r"^❌ Hủy$"), cmd_cancel)],
    )
    return create_conv, login_conv, rename_conv, search_conv


async def post_init(app: Application):
    app.create_task(poll_loop(app))
    try:
        await app.bot.send_message(
            chat_id=ADMIN_ID,
            text="🤖 <b>Mail OTP Bot đã khởi động!</b>\n"
                 "Sẵn sàng tạo mail & nhận OTP. Bấm /menu nhé.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
    except Exception as exc:
        logger.warning("khong gui duoc tin nhan khoi dong: %s", exc)


def main():
    global BOT_TOKEN
    BOT_TOKEN = _load_token()
    if not BOT_TOKEN:
        print("=" * 60)
        print("CHUA CAU HINH TOKEN!")
        print("- Deploy cloud (Render): dat bien moi truong BOT_TOKEN")
        print("- Chay local: tao file token.txt cung thu muc, dan token vao")
        print("  (lay token tu @BotFather -> /mybots -> chon bot -> API Token)")
        print("=" * 60)
        raise SystemExit(1)
    # chi cho 1 instance chay -> tranh loi Conflict
    ok, other_pid = acquire_lock()
    if not ok:
        print("=" * 60)
        print(f"BOT DANG CHAY O TIEN TRINH KHAC (PID {other_pid}).")
        print("Telegram chi cho 1 instance polling 1 luc.")
        print("Tat bot cu truoc, Windows chay:  taskkill /F /IM python.exe")
        print("=" * 60)
        raise SystemExit(2)
    atexit.register(lambda: LOCK_PATH.unlink(missing_ok=True))
    # Lan deploy dau tien: dung lai DB tu seed.sql (du lieu goc cua user)
    _seed = Path(DATA_DIR) / "seed.sql"
    if not Path(DB_PATH).exists() and _seed.exists():
        try:
            Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
            _con = sqlite3.connect(DB_PATH)
            try:
                _con.executescript(_seed.read_text(encoding="utf-8"))
                _con.commit()
            finally:
                _con.close()
            logger.info("Da khoi phuc du lieu tu seed.sql")
        except Exception as exc:
            logger.warning("Khoi phuc seed.sql loi: %s", exc)
    init_db()
    # gia tri mac dinh neu chua co
    if not get_setting("poll_interval"):
        set_setting("poll_interval", str(POLL_INTERVAL))
    if not get_setting("default_provider"):
        set_setting("default_provider", DEFAULT_PROVIDER)
    if not get_setting("notify_global"):
        set_setting("notify_global", "1" if NOTIFY_ENABLED else "0")
    if not get_setting("otp_only"):
        set_setting("otp_only", "1" if OTP_ONLY_MODE else "0")
    if not get_setting("short_domain"):
        set_setting("short_domain", "0")
    if not get_setting("digest_mode"):
        set_setting("digest_mode", "1")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    create_conv, login_conv, rename_conv, search_conv = build_conversations()
    app.add_handler(create_conv)
    app.add_handler(login_conv)
    app.add_handler(rename_conv)
    app.add_handler(search_conv)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", btn_stats))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("export", btn_export))
    app.add_handler(CommandHandler("backup", btn_backup))
    app.add_handler(CommandHandler("restore", cmd_restore_hint))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("cancel", cmd_cancel))

    app.add_handler(MessageHandler(
        filters.Regex(r"^⚡ Tạo Mail Nhanh$") & filters.ChatType.PRIVATE,
        btn_quick_create))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📥 Check OTP$") & filters.ChatType.PRIVATE,
        btn_check_now))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📧 Hộp Thư Của Tôi$") & filters.ChatType.PRIVATE,
        btn_my_mailbox))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📬 Danh Sách Mail$") & filters.ChatType.PRIVATE,
        btn_mailbox_list))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📊 Thống Kê$") & filters.ChatType.PRIVATE,
        btn_stats))
    app.add_handler(MessageHandler(
        filters.Regex(r"^🌐 Đổi Provider$") & filters.ChatType.PRIVATE,
        btn_change_provider))
    app.add_handler(MessageHandler(
        filters.Regex(r"^⚙️ Cài Đặt$") & filters.ChatType.PRIVATE,
        btn_settings))
    app.add_handler(MessageHandler(
        filters.Regex(r"^🖥️ Web Dashboard$") & filters.ChatType.PRIVATE,
        btn_webdash))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📖 Hướng Dẫn$") & filters.ChatType.PRIVATE,
        btn_guide))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📦 Tạo nhiều mail$") & filters.ChatType.PRIVATE,
        btn_batch))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📤 Xuất File$") & filters.ChatType.PRIVATE,
        btn_export))
    app.add_handler(MessageHandler(
        filters.Regex(r"^🕘 Lịch sử OTP$") & filters.ChatType.PRIVATE,
        btn_history))
    app.add_handler(MessageHandler(
        filters.Regex(r"^💾 Sao lưu$") & filters.ChatType.PRIVATE,
        btn_backup))

    app.add_handler(CallbackQueryHandler(on_callback))
    # Nhan file .db de khoi phuc du lieu (admin gui truc tiep vao chat)
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.ChatType.PRIVATE, restore_db))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
                                    unknown_text))

    app.add_error_handler(on_error)

    logger.info("Bot starting... admin=%s", ADMIN_ID)
    try:
        start_webdash()
    except Exception as exc:
        logger.warning("Web dashboard khong khoi dong duoc: %s", exc)
    # Tu dong sao luu DB moi ngay gui ve cho admin
    # (phong khi deploy lai bi mat du lieu tren o dia tam cua host free)
    try:
        _jq = app.job_queue
    except Exception:
        _jq = None
    if _jq is not None:
        async def _auto_backup(context: ContextTypes.DEFAULT_TYPE):
            try:
                _p = Path(DB_PATH)
                if _p.exists():
                    with open(_p, "rb") as _f:
                        await context.bot.send_document(
                            chat_id=ADMIN_ID, document=_f,
                            filename="mailbot_autobackup_%s.db"
                            % time.strftime("%Y%m%d"),
                            caption="💾 Tự động sao lưu hằng ngày.")
            except Exception as exc:
                logger.warning("auto backup loi: %s", exc)
        _jq.run_repeating(_auto_backup, interval=86400, first=3600)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


# ══════════════ V5 PRO: WEB DASHBOARD ══════════════
WEB_PORT = 8092

@admin_only
async def btn_webdash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Khi chay tren Render: gui link public, kem key bao mat
    _public = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    _dkey = os.environ.get("DASH_KEY", "").strip()
    if _public:
        _url = _public + (f"/?key={_dkey}" if _dkey else "/")
        _open = f"Mở: {_url}"
    else:
        _open = f"Mở: <code>http://127.0.0.1:{WEB_PORT}</code>"
    await update.effective_message.reply_text(
        "🖥️ <b>WEB DASHBOARD</b> — quản lý mail trên trình duyệt\n\n"
        f"{_open}\n\n"
        "• Xem tất cả hộp thư, bấm đọc từng mail\n"
        "• OTP tự tách sẵn, chạm để copy\n"
        "• Tự làm mới mỗi 20 giây",
        parse_mode=ParseMode.HTML)


def _web_run(coro):
    return asyncio.run(coro)


def _web_find_mailbox(address):
    address = (address or "").strip().lower()
    for mb in list_mailboxes():
        if (mb["address"] or "").strip().lower() == address:
            return mb
    return None


WEB_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAIL REG PRO • TM MEDIA</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#070b16;color:#e8edff;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
.aurora{position:fixed;inset:0;z-index:-1;overflow:hidden}
.aurora i{position:absolute;width:560px;height:560px;border-radius:50%;filter:blur(120px);opacity:.3;animation:drift 20s ease-in-out infinite alternate}
.aurora i:nth-child(1){background:#7c3aed;top:-140px;left:-120px}
.aurora i:nth-child(2){background:#22d3ee;bottom:-160px;right:-100px;animation-delay:-7s}
.aurora i:nth-child(3){background:#ec4899;top:38%;left:52%;width:440px;height:440px;animation-delay:-13s;opacity:.18}
@keyframes drift{from{transform:translate(0,0) scale(1)}to{transform:translate(100px,70px) scale(1.18)}}
.wrap{max-width:1180px;margin:0 auto;padding:26px 20px 60px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:4px}
header h1{font-size:28px;background:linear-gradient(90deg,#a78bfa,#22d3ee);-webkit-background-clip:text;background-clip:text;color:transparent}
header .tm{font-size:13px;color:#8b98b8;letter-spacing:3px}
header .ver{font-size:12px;color:#22d3ee;border:1px solid rgba(34,211,238,.4);padding:3px 10px;border-radius:20px}
.sub{color:#8b98b8;font-size:13px;margin-bottom:18px}
.cols{display:grid;grid-template-columns:300px 1fr;gap:14px}
@media(max-width:800px){.cols{grid-template-columns:1fr}}
.panel{background:rgba(20,27,50,.72);border:1px solid rgba(124,58,237,.25);border-radius:16px;
padding:16px;backdrop-filter:blur(10px);min-height:200px}
.panel h2{font-size:15px;margin-bottom:10px;color:#c4b5fd}
.mb{padding:10px 12px;border-radius:10px;cursor:pointer;font-size:13px;margin-bottom:6px;
border:1px solid transparent;word-break:break-all;transition:.15s}
.mb:hover{background:rgba(124,58,237,.12)}
.mb.on{background:rgba(124,58,237,.2);border-color:rgba(124,58,237,.5)}
.mb small{color:#8b98b8;display:block;font-size:11px}
.msg{padding:12px;border-bottom:1px solid rgba(124,58,237,.15);cursor:pointer;transition:.15s}
.msg:hover{background:rgba(124,58,237,.08)}
.msg .s{font-size:14px;font-weight:600;margin-bottom:4px}
.msg .m{font-size:12px;color:#8b98b8}
.msg .otp{display:inline-block;background:rgba(34,211,238,.15);color:#22d3ee;border:1px solid rgba(34,211,238,.4);
border-radius:8px;padding:2px 10px;font-family:monospace;font-size:14px;margin-top:6px;cursor:pointer}
#detail{position:fixed;inset:0;background:rgba(4,6,12,.7);display:none;align-items:center;justify-content:center;z-index:50;padding:20px}
#detail.on{display:flex}
#detail .box{background:rgba(17,23,42,.97);border:1px solid rgba(124,58,237,.4);border-radius:18px;
max-width:640px;width:100%;max-height:88vh;overflow-y:auto;padding:24px;animation:pop .25s}
@keyframes pop{from{opacity:0;transform:scale(.95)}to{opacity:1}}
.x{float:right;cursor:pointer;color:#8b98b8;font-size:18px}
pre{white-space:pre-wrap;font-size:13px;color:#c9d4f2;margin-top:10px;line-height:1.6}
.ref{font-size:12px;color:#8b98b8;text-align:right;margin-top:8px}
::-webkit-scrollbar{width:10px}::-webkit-scrollbar-track{background:#070b16}
::-webkit-scrollbar-thumb{background:linear-gradient(#7c3aed,#22d3ee);border-radius:8px}
</style>
</head>
<body>
<div class="aurora"><i></i><i></i><i></i></div>
<div class="wrap">
<header><h1>📧 MAIL REG PRO</h1><span class="tm">TM MEDIA</span><span class="ver">v5.0</span></header>
<div class="sub">Bấm vào hộp thư bên trái để xem mail • tự làm mới mỗi 20 giây</div>
<div class="cols">
<div class="panel"><h2>📬 Hộp thư</h2><div id="mbs"><div class="ref">Đang tải...</div></div></div>
<div class="panel"><h2 id="inboxt">✉️ Tin nhắn</h2><div id="msgs"><div class="ref">Chọn một hộp thư.</div></div></div>
</div>
</div>
<div id="detail"><div class="box"><span class="x" id="xbtn">✖</span><div id="dbox"></div></div></div>
<script>
const $=id=>document.getElementById(id);
let CUR='';
async function api(p){const k=new URLSearchParams(location.search).get('key');const u=k?p+(p.includes('?')?'&':'?')+'key='+encodeURIComponent(k):p;const r=await fetch(u);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
async function loadMbs(){
  try{
    const j=await api('/api/mailboxes');
    $('mbs').innerHTML=j.items.map(m=>
      '<div class="mb'+(m.address===CUR?' on':'')+'" data-a="'+esc(m.address)+'">'+esc(m.address)+
      '<small>'+esc(m.backend)+'</small></div>').join('')||'<div class="ref">Chưa có hộp thư nào.</div>';
    document.querySelectorAll('.mb').forEach(e=>{e.onclick=()=>{CUR=e.dataset.a;loadMbs();loadInbox()}});
  }catch(e){$('mbs').innerHTML='<div class="ref">Lỗi tải.</div>'}
}
async function loadInbox(){
  if(!CUR)return;
  $('inboxt').textContent='✉️ '+CUR;
  $('msgs').innerHTML='<div class="ref">Đang tải...</div>';
  try{
    const j=await api('/api/inbox?a='+encodeURIComponent(CUR));
    $('msgs').innerHTML=j.items.map(m=>
      '<div class="msg" data-mid="'+m.id+'"><div class="s">'+esc(m.subject||'(không tiêu đề)')+'</div>'+
      '<div class="m">'+esc(m.sender)+' • '+esc(m.date)+'</div>'+
      (m.otp?'<span class="otp" title="Chạm để copy">'+esc(m.otp)+'</span>':'')+'</div>').join('')
      ||'<div class="ref">Hộp thư trống.</div>';
    document.querySelectorAll('.msg').forEach(e=>{e.onclick=()=>readMsg(e.dataset.mid)});
    document.querySelectorAll('.otp').forEach(e=>{e.onclick=ev=>{ev.stopPropagation();navigator.clipboard.writeText(e.textContent)}});
  }catch(e){$('msgs').innerHTML='<div class="ref">Lỗi tải inbox.</div>'}
}
async function readMsg(mid){
  const j=await api('/api/read?a='+encodeURIComponent(CUR)+'&mid='+encodeURIComponent(mid));
  $('dbox').innerHTML='<h3>'+esc(j.subject||'(không tiêu đề)')+'</h3>'+
    '<div class="m" style="font-size:12px;color:#8b98b8">'+esc(j.sender)+' • '+esc(j.date)+'</div>'+
    (j.otp?'<div style="margin:10px 0"><span class="otp" style="font-size:20px" onclick="navigator.clipboard.writeText(this.textContent)">'+esc(j.otp)+'</span></div>':'')+
    '<pre>'+esc(j.body||'')+'</pre>';
  $('detail').classList.add('on');
}
$('xbtn').onclick=()=>$('detail').classList.remove('on');
$('detail').onclick=e=>{if(e.target.id==='detail')$('detail').classList.remove('on')};
loadMbs();
setInterval(()=>{loadMbs();if(CUR)loadInbox()},20000);
</script>
</body>
</html>"""


def start_webdash():
    if not HAS_FLASK:
        logger.warning("Thieu flask -> bo qua web dashboard.")
        return
    wapp = Flask("mailregpro_web")

    @wapp.route("/health")
    def health():
        return jsonify({"ok": True, "bot": "mail-reg-pro"})

    @wapp.before_request
    def _dash_auth():
        # Khi public len mang (Render): neu co dat DASH_KEY thi moi route
        # (tru /health) bat buoc phai co ?key= trung khop
        if _rq.path == "/health":
            return None
        dk = os.environ.get("DASH_KEY", "").strip()
        if dk and _rq.args.get("key") != dk:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return None

    @wapp.route("/")
    def idx():
        return WEB_HTML

    @wapp.route("/api/mailboxes")
    def api_mbs():
        items = [{"id": mb["id"], "address": mb["address"],
                  "backend": mb["backend"]} for mb in list_mailboxes()]
        return jsonify({"ok": True, "items": items})

    @wapp.route("/api/inbox")
    def api_inbox():
        mb = _web_find_mailbox(_rq.args.get("a"))
        if not mb:
            return jsonify({"ok": True, "items": []})
        creds = creds_from_row(mb)
        backend = manager.get(creds.backend)
        try:
            items = _web_run(safe_list_messages(creds, mb["id"]))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:200]})
        out = []
        for it in items[:50]:
            otp, _ = extract_best_otp((it.subject or "") + "\n" + (it.preview or ""))
            out.append({"id": it.msg_id, "sender": it.sender,
                        "subject": it.subject, "date": it.date, "otp": otp})
        return jsonify({"ok": True, "items": out})

    @wapp.route("/api/read")
    def api_read():
        mb = _web_find_mailbox(_rq.args.get("a"))
        if not mb:
            return jsonify({"ok": False}), 404
        creds = creds_from_row(mb)
        backend = manager.get(creds.backend)
        try:
            item = _web_run(backend.read_message(creds, _rq.args.get("mid")))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:200]})
        full = (item.subject or "") + "\n" + (item.body_text or "")
        otp, _ = extract_best_otp(full)
        return jsonify({"ok": True, "sender": item.sender,
                        "subject": item.subject, "date": item.date,
                        "body": (item.body_text or "")[:8000], "otp": otp})

    # Tren Render: bind 0.0.0.0 + cong PORT do Render cap
    # (UptimeRobot ping /health de giu bot khong ngu)
    _whost = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    _wport = int(os.environ.get("PORT", WEB_PORT))
    import threading as _th
    t = _th.Thread(target=lambda: wapp.run(host=_whost, port=_wport,
                                           debug=False, use_reloader=False),
                   daemon=True)
    t.start()
    logger.info("Web dashboard: http://%s:%s", _whost, _wport)


if __name__ == "__main__":
    main()
