"""
Telegram userbot: APK va havolalarni zudlik bilan o'chiradi va adminga bot orqali xabar beradi.

Ishga tushirish:
    pip install -r requirements.txt
    python bot.py          # birinchi marta telefon raqam va kod so'raydi
"""
import asyncio
import logging
import re

import aiohttp
from telethon import TelegramClient, events
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageEntityTextUrl,
    MessageEntityUrl,
)

API_ID = 39137299
API_HASH = "e67d098704ca5ce1f4a33a2b33e97f89"
BOT_TOKEN = "8246378380:AAHsa6DjVrXZwXZODaPnbX98GlyI4Hx9Z8Q"
ADMIN_ID = 8426582765
SESSION = "userbot_session"

# Ruxsat etilgan domenlar (vergul bilan), masalan: "google.com,github.com". Bo'sh bo'lsa hamma havola o'chiriladi.
ALLOWED_DOMAINS: list[str] = []  # masalan: ["github.com", "google.com"]
# Ishonchli yuboruvchilar ID si (o'chirilmaydi), vergul bilan.
TRUSTED_IDS: set[int] = set()  # o'chirilmaydigan yuboruvchi ID lari
TRUSTED_IDS.add(ADMIN_ID)

APK_EXTENSIONS = (".apk", ".xapk", ".apks", ".apkm", ".aab")
APK_MIME = {"application/vnd.android.package-archive"}
URL_RE = re.compile(
    r"(?:https?://|www\.|t\.me/|tg://)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|uz|ru|io|me|xyz|top|cc|link|app|apk)\b/?\S*",
    re.IGNORECASE,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("userbot")

client = TelegramClient(SESSION, API_ID, API_HASH)
_http: aiohttp.ClientSession | None = None
_seen: set[tuple[int, int]] = set()


async def notify_admin(text: str) -> None:
    """Bot API orqali adminga xabar yuboradi."""
    global _http
    if _http is None:
        _http = aiohttp.ClientSession()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
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
            if attr.file_name.lower().endswith(APK_EXTENSIONS):
                return True
    return False


def _domain(url: str) -> str:
    url = re.sub(r"^(?:https?://|tg://)", "", url.strip(), flags=re.I)
    url = re.sub(r"^www\.", "", url, flags=re.I)
    return re.split(r"[/?#:]", url, maxsplit=1)[0].lower()


def _allowed(url: str) -> bool:
    d = _domain(url)
    return any(d == a or d.endswith("." + a) for a in ALLOWED_DOMAINS)


def find_links(message) -> list[str]:
    links: list[str] = []
    text = message.raw_text or ""
    for ent, part in message.get_entities_text() if message.entities else []:
        if isinstance(ent, MessageEntityTextUrl):
            links.append(ent.url)
        elif isinstance(ent, MessageEntityUrl):
            links.append(part)
    links += URL_RE.findall(text)
    # Tugmalardagi havolalar
    if message.buttons:
        for row in message.buttons:
            for btn in row:
                if getattr(btn, "url", None):
                    links.append(btn.url)
    unique = list(dict.fromkeys(links))
    return [u for u in unique if not _allowed(u)]


async def handle(event) -> None:
    msg = event.message
    key = (event.chat_id, msg.id)
    if key in _seen:
        return
    if event.sender_id in TRUSTED_IDS:
        return

    reasons: list[str] = []
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

    sender = await event.get_sender()
    chat = await event.get_chat()
    sender_name = " ".join(
        filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])
    ) or getattr(sender, "title", None) or "Noma'lum"
    username = f"@{sender.username}" if getattr(sender, "username", None) else "yo'q"
    chat_name = getattr(chat, "title", None) or "Shaxsiy chat"

    lines = [
        f"🛡 <b>{' va '.join(reasons).capitalize()} keldi, {status}</b>",
        f"👤 Yuboruvchi: {sender_name} ({username}), ID: <code>{event.sender_id}</code>",
        f"💬 Chat: {chat_name}",
    ]
    if links:
        shown = "\n".join(f"• <code>{u[:120]}</code>" for u in links[:5])
        lines.append(f"🔗 Havolalar:\n{shown}")
    if is_apk(msg):
        name = next(
            (a.file_name for a in msg.document.attributes if isinstance(a, DocumentAttributeFilename)),
            "nomsiz",
        )
        lines.append(f"📦 Fayl: <code>{name}</code>")
    await notify_admin("\n".join(lines))
    log.info("%s | chat=%s sender=%s", status, event.chat_id, event.sender_id)


@client.on(events.NewMessage(incoming=True))
async def on_new(event):
    await handle(event)


@client.on(events.MessageEdited(incoming=True))
async def on_edit(event):
    await handle(event)


async def main() -> None:
    await client.start()
    me = await client.get_me()
    log.info("Userbot ishga tushdi: %s (%s)", me.first_name, me.id)
    await notify_admin("✅ Userbot ishga tushdi va chatlarni kuzatmoqda.")
    try:
        await client.run_until_disconnected()
    finally:
        if _http:
            await _http.close()


if __name__ == "__main__":
    asyncio.run(main())
