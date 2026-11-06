"""
Telegram userbot: APK va havolalarni zudlik bilan o'chiradi va adminga bot orqali xabar beradi.

Birinchi marta ishga tushganda bot ADMIN ga (bot orqali) telefon raqam va kod so'raydi,
akkauntga "Samsung Galaxy S23 Ultra" qurilmasi nomidan kiradi. Oldin botga /start yuboring.
"""
import asyncio
import logging
import os
import re
from typing import Optional

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
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
SESSION_FILE = os.environ.get("SESSION_FILE", "session.txt")
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()
if not SESSION_STRING and os.path.exists(SESSION_FILE):
    with open(SESSION_FILE, encoding="utf-8") as _f:
        SESSION_STRING = _f.read().strip()
# Ixtiyoriy: sessiya avtomatik Render Environment'ga saqlansin desangiz (redeploydan keyin ham yo'qolmaydi)
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "")

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
    return TelegramClient(
        StringSession(SESSION_STRING),
        API_ID,
        API_HASH,
        device_model="Samsung Galaxy S23 Ultra",
        system_version="Android 14",
        app_version="10.14.5",
        lang_code="uz",
        system_lang_code="uz",
    )


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


_offset = 0


async def bot_api(method: str, timeout: int = 15, **payload):
    global _http
    if _http is None or _http.closed:
        _http = aiohttp.ClientSession()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with _http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        data = await resp.json()
    return data.get("result") if data.get("ok") else None


async def flush_updates() -> None:
    global _offset
    res = await bot_api("getUpdates", offset=-1, timeout=0)
    if res:
        _offset = res[-1]["update_id"] + 1


async def get_reply(prompt: str, wait: int = 900) -> Optional[str]:
    """Adminga savol yuboradi, javobini kutadi va javob xabarini (maxfiylik uchun) o'chiradi."""
    global _offset
    await notify_admin(prompt)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + wait
    while loop.time() < deadline:
        try:
            updates = await bot_api("getUpdates", timeout=40, offset=_offset, **{"allowed_updates": ["message"]})
        except Exception as exc:  # noqa: BLE001
            log.warning("getUpdates xatosi: %s", exc)
            await asyncio.sleep(3)
            continue
        for upd in updates or []:
            _offset = upd["update_id"] + 1
            m = upd.get("message") or {}
            if m.get("from", {}).get("id") != ADMIN_ID or "text" not in m:
                continue
            text = m["text"].strip()
            if text.startswith("/start"):
                await notify_admin(prompt)
                continue
            try:
                await bot_api("deleteMessage", chat_id=ADMIN_ID, message_id=m["message_id"])
            except Exception:  # noqa: BLE001
                pass
            return text
    return None


async def save_session() -> None:
    s = client.session.save()
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(s)
    except Exception as exc:  # noqa: BLE001
        log.warning("Session faylga yozilmadi: %s", exc)
    if RENDER_API_KEY and RENDER_SERVICE_ID and _http:
        try:
            async with _http.put(
                f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars/SESSION_STRING",
                headers={"Authorization": f"Bearer {RENDER_API_KEY}", "Content-Type": "application/json"},
                json={"value": s},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                log.info("Render env yangilandi: %s", r.status)
        except Exception as exc:  # noqa: BLE001
            log.warning("Render env yangilanmadi: %s", exc)
    await notify_admin(
        "✅ Akkauntga kirildi (Samsung Galaxy S23 Ultra).\n\n"
        "Qayta deploydan keyin ham ishlashi uchun Render → Environment → <code>SESSION_STRING</code> ga "
        "quyidagini qo'ying (keyin shu xabarni o'chiring, hech kimga bermang):\n\n"
        f"<code>{s}</code>"
    )


async def interactive_login() -> None:
    """Telefon raqam, kod va (kerak bo'lsa) 2FA parolni bot orqali admindan so'raydi."""
    await flush_updates()
    while True:
        phone_text = await get_reply(
            "📱 Userbot uchun akkaunt kerak.\nTelefon raqamingizni yuboring (masalan: <code>+998901234567</code>):"
        )
        if not phone_text:
            continue
        phone = "+" + re.sub(r"\D", "", phone_text)
        try:
            sent = await client.send_code_request(phone)
        except FloodWaitError as exc:
            await notify_admin(f"⏳ Telegram {exc.seconds} soniya kutishni so'radi.")
            await asyncio.sleep(exc.seconds + 3)
            continue
        except Exception as exc:  # noqa: BLE001
            await notify_admin(f"❌ Kod yuborilmadi: {type(exc).__name__}. Raqamni qayta yuboring.")
            continue

        while True:
            code_text = await get_reply(
                "🔑 Telegramga kelgan kodni yuboring.\n"
                "⚠️ Raqamlar orasiga <b>tire</b> qo'ying, masalan: <code>1-2-3-4-5</code>. "
                "Aks holda Telegram kodni xavfsizlik uchun bekor qiladi."
            )
            if not code_text:
                break
            code = re.sub(r"\D", "", code_text)
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                await save_session()
                return
            except SessionPasswordNeededError:
                while True:
                    pw = await get_reply("🔐 Ikki bosqichli parolni (2FA) yuboring:")
                    if not pw:
                        continue
                    try:
                        await client.sign_in(password=pw)
                        await save_session()
                        return
                    except PasswordHashInvalidError:
                        await notify_admin("❌ Parol noto'g'ri, qayta yuboring.")
            except PhoneCodeInvalidError:
                await notify_admin("❌ Kod noto'g'ri. Qayta yuboring.")
            except PhoneCodeExpiredError:
                await notify_admin("⌛ Kod eskirdi. Yangi kod yuboriladi.")
                break
            except Exception as exc:  # noqa: BLE001
                await notify_admin(f"❌ Xato: {type(exc).__name__}. Boshidan boshlaymiz.")
                break


async def main() -> None:
    global client
    await start_health_server()

    client = make_client()
    client.add_event_handler(on_new, events.NewMessage(incoming=True))
    client.add_event_handler(on_edit, events.MessageEdited(incoming=True))
    await client.connect()

    if not await client.is_user_authorized():
        log.info("Session yo'q, bot orqali login so'raladi")
        await interactive_login()

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
    asyncio.run(runner())
