"""
Telegram userbot: APK va havolalarni zudlik bilan o'chiradi va adminga bot orqali xabar beradi.

1) Session olish (BIR MARTA, o'z kompyuter/Termux'ingizda):
       pip install -r requirements.txt
       python bot.py login
   Chiqqan uzun matnni Render -> Environment -> SESSION_STRING ga qo'ying.

2) Render'da ishga tushirish:
       Start command: python bot.py
"""
import asyncio
import logging
import os
import re
import sys
from typing import Optional

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageEntityTextUrl,
    MessageEntityUrl,
)

# ----------------------------- SOZLAMALAR -----------------------------
API_ID = int(os.environ.get("API_ID", "39137299"))
API_HASH = os.environ.get("API_HASH", "e67d098704ca5ce1f4a33a2b33e97f89")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8246378380:AAHsa6DjVrXZwXZODaPnbX98GlyI4Hx9Z8Q")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8426582765"))

# Render'da SESSION_STRING environment variable ga qo'ying (python bot.py login orqali olinadi).
# Bu yerga to'g'ridan-to'g'ri ham yopishtirishingiz mumkin:
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()

# Ruxsat etilgan domenlar. Bo'sh bo'lsa hamma havola o'chiriladi.
ALLOWED_DOMAINS: list = []  # masalan: ["github.com", "google.com"]
# O'chirilmaydigan yuboruvchilar ID si.
TRUSTED_IDS: set = {ADMIN_ID}
# ---------------------------------------------------------------------

APK_EXTENSIONS = (".apk", ".xapk", ".apks", ".apkm", ".aab")
APK_MIME = {"application/vnd.android.package-archive"}
URL_RE = re.compile(
    r"(?:https?://|www\.|t\.me/|tg://)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|uz|ru|io|me|xyz|top|cc|link|app|apk)\b/?\S*",
    re.IGNORECASE,
)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger("userbot")

_http: Optional[aiohttp.ClientSession] = None
_seen: set = set()
client: Optional[TelegramClient] = None


def make_client() -> TelegramClient:
    session = StringSession(SESSION_STRING) if SESSION_STRING else "userbot_session"
    return TelegramClient(session, API_ID, API_HASH)


async def notify_admin(text: str) -> None:
    """Bot API orqali adminga xabar yuboradi."""
    global _http
    try:
        if _http is None or _http.closed:
            _http = aiohttp.ClientSession()
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        async with _http.post(
            url,
            json={"chat_id": ADMIN_ID, "text": text, "parse_mode": "HTML"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                log.error("Bot xabari yuborilmadi: %s %s", resp.status, await resp.text())
    except Exception as exc:  # noqa: BLE001
        log.error("Bot API xatosi: %s", exc)


def is_apk(message) -> bool:
    doc = getattr(message, "document", None)
    if not doc:
        return False
    if doc.mime_type in APK_MIME:
        return True
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            if (attr.file_name or "").lower().endswith(APK_EXTENSIONS):
                return True
    return False


def _domain(url: str) -> str:
    url = re.sub(r"^(?:https?://|tg://)", "", url.strip(), flags=re.I)
    url = re.sub(r"^www\.", "", url, flags=re.I)
    return re.split(r"[/?#:]", url, maxsplit=1)[0].lower()


def _allowed(url: str) -> bool:
    d = _domain(url)
    return any(d == a or d.endswith("." + a) for a in ALLOWED_DOMAINS)


def find_links(message) -> list:
    links: list = []
    text = message.raw_text or ""
    try:
        if message.entities:
            for ent, part in message.get_entities_text():
                if isinstance(ent, MessageEntityTextUrl):
                    links.append(ent.url)
                elif isinstance(ent, MessageEntityUrl):
                    links.append(part)
    except Exception as exc:  # noqa: BLE001
        log.warning("Entity o'qishda xato: %s", exc)
    links += URL_RE.findall(text)
    try:
        if message.buttons:
            for row in message.buttons:
                for btn in row:
                    if getattr(btn, "url", None):
                        links.append(btn.url)
    except Exception as exc:  # noqa: BLE001
        log.warning("Tugma o'qishda xato: %s", exc)
    unique = list(dict.fromkeys(links))
    return [u for u in unique if not _allowed(u)]


async def handle(event) -> None:
    try:
        msg = event.message
        key = (event.chat_id, msg.id)
        if key in _seen:
            return
        if event.sender_id in TRUSTED_IDS:
            return

        reasons: list = []
        if is_apk(msg):
            reasons.append("APK fayl")
        links = find_links(msg)
        if links:
            reasons.append("havola")
        if not reasons:
            return

        _seen.add(key)
        if len(_seen) > 5000:
            _seen.clear()

        try:
            await client.delete_messages(event.chat_id, [msg.id], revoke=True)
            status = "muvaffaqiyatli o'chirildi"
        except Exception as exc:  # noqa: BLE001
            status = f"O'CHIRIB BO'LMADI ({type(exc).__name__}: {exc})"
            log.error("O'chirishda xato: %s", exc)

        try:
            sender = await event.get_sender()
            chat = await event.get_chat()
        except Exception:  # noqa: BLE001
            sender, chat = None, None
        sender_name = (
            " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]))
            or getattr(sender, "title", None)
            or "Noma'lum"
        )
        uname = getattr(sender, "username", None)
        username = f"@{uname}" if uname else "yo'q"
        chat_name = getattr(chat, "title", None) or "Shaxsiy chat"

        lines = [
            f"🛡 <b>{' va '.join(reasons).capitalize()} keldi, {status}</b>",
            f"👤 Yuboruvchi: {sender_name} ({username}), ID: <code>{event.sender_id}</code>",
            f"💬 Chat: {chat_name}",
        ]
        if links:
            shown = "\n".join(
                f"• <code>{u[:120].replace('<', '&lt;').replace('>', '&gt;')}</code>" for u in links[:5]
            )
            lines.append(f"🔗 Havolalar:\n{shown}")
        if is_apk(msg):
            name = next(
                (a.file_name for a in msg.document.attributes if isinstance(a, DocumentAttributeFilename)),
                "nomsiz",
            )
            lines.append(f"📦 Fayl: <code>{name}</code>")
        await notify_admin("\n".join(lines))
        log.info("%s | chat=%s sender=%s", status, event.chat_id, event.sender_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("handle xatosi: %s", exc)


async def on_new(event):
    await handle(event)


async def on_edit(event):
    await handle(event)


async def start_health_server() -> None:
    """Render 'Web Service' bo'lsa port ochiq bo'lishi kerak. Background Worker'da zarar qilmaydi."""
    port = int(os.environ.get("PORT", "10000"))

    async def ok(_request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", ok)
    app.router.add_get("/health", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Health server %s portda", port)


async def login_mode() -> None:
    """Lokal ishlatiladi: telefon raqam va kod so'raydi, SESSION_STRING chiqaradi."""
    async with TelegramClient(StringSession(), API_ID, API_HASH) as c:
        print("\n===== SESSION_STRING (butunlay nusxa oling) =====\n")
        print(c.session.save())
        print("\n=================================================")
        print("Buni Render -> Environment -> SESSION_STRING ga qo'ying. Hech kimga bermang!")


async def main() -> None:
    global client
    await start_health_server()

    if not SESSION_STRING:
        msg = (
            "SESSION_STRING topilmadi. Lokal kompyuterda `python bot.py login` ni ishga tushiring, "
            "chiqqan matnni Render'da SESSION_STRING environment variable ga qo'ying."
        )
        log.error(msg)
        await notify_admin("⚠️ " + msg)
        while True:  # qayta-qayta crash bo'lmasligi uchun kutib turadi
            await asyncio.sleep(3600)

    client = make_client()
    client.add_event_handler(on_new, events.NewMessage(incoming=True))
    client.add_event_handler(on_edit, events.MessageEdited(incoming=True))

    await client.connect()
    if not await client.is_user_authorized():
        msg = "SESSION_STRING yaroqsiz yoki eskirgan. `python bot.py login` bilan yangisini oling."
        log.error(msg)
        await notify_admin("⚠️ " + msg)
        while True:
            await asyncio.sleep(3600)

    me = await client.get_me()
    log.info("Userbot ishga tushdi: %s (%s)", me.first_name, me.id)
    await notify_admin("✅ Userbot ishga tushdi va chatlarni kuzatmoqda.")
    try:
        await client.run_until_disconnected()
    finally:
        if _http and not _http.closed:
            await _http.close()


async def runner() -> None:
    while True:
        try:
            await main()
            return
        except FloodWaitError as exc:
            log.warning("FloodWait: %s soniya kutaman", exc.seconds)
            await asyncio.sleep(exc.seconds + 5)
        except Exception as exc:  # noqa: BLE001
            log.exception("Kutilmagan xato, 10 soniyadan keyin qayta uriniladi: %s", exc)
            await asyncio.sleep(10)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        asyncio.run(login_mode())
    else:
        asyncio.run(runner())
