# main.py (FINAL VERSION – default gpt-4o)
import os
import logging
import requests
from fastapi import FastAPI, Request, BackgroundTasks
import openai
from typing import Optional

# ======================================================
# LOGGING
# ======================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("ssm_bot")

# ======================================================
# ENV CONFIG
# ======================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Default model = gpt-4o  ← (mengikut permintaan awak)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Temperature default lebih natural
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
PORT = int(os.getenv("PORT", "8000"))

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.error("Missing TELEGRAM_BOT_TOKEN or OPENAI_API_KEY")
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and OPENAI_API_KEY in Railway Variables")

openai.api_key = OPENAI_API_KEY
TG_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI(title="SSM Telegram Bot")

# ======================================================
# TELEGRAM SEND
# ======================================================
def send_telegram_message(chat_id: int, text: str, parse_mode: Optional[str] = None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(f"{TG_API_URL}/sendMessage", json=payload, timeout=10)
        if not resp.ok:
            logger.error("sendMessage failed: %s %s", resp.status_code, resp.text)
        else:
            logger.info("sendMessage OK chat_id=%s len=%d", chat_id, len(text))
    except Exception:
        logger.exception("send_telegram_message error")

# ======================================================
# SYSTEM INSTRUCTION LOADER
# ======================================================
SYSTEM_INSTRUCTION = ""
try:
    with open("instructions.txt", "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read().strip()
        logger.info("Loaded instructions.txt (%d chars)", len(SYSTEM_INSTRUCTION))
except Exception:
    SYSTEM_INSTRUCTION = (
        "Anda ialah pembantu maya Penguatkuasa SSM Johor. "
        "Berikan jawapan ringkas, jelas, profesional dan mesra."
    )
    logger.warning("instructions.txt not found — using fallback instruction")

# ======================================================
# BUILD OPENAI MESSAGE FORMAT
# ======================================================
def build_openai_messages(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_text}
    ]

# ======================================================
# CALL OPENAI
# ======================================================
def call_openai(messages):
    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=OPENAI_TEMPERATURE,
        max_tokens=800,
        timeout=30
    )
    return resp.choices[0].message["content"].strip()

# ======================================================
# WELCOME MESSAGE
# ======================================================
WELCOME_TEXT = (
    "Selamat datang ke Pembantu Maya Bahagian Penguatkuasa SSM Johor.\n\n"
    "Saya boleh bantu beri penerangan umum mengenai kompaun, pemeriksaan, pematuhan, "
    "dan proses proses pembayaran kompaun.\n\n"
    "Nota: Saya tidak mempunyai akses kepada sistem dalaman seperti e-Compound."
)

WELCOME_TRIGGERS = {
    "/start", "start", "mula", "hi", "hello",
    "assalamualaikum", "salam", "ssm", "penguatkuasa"
}

def is_welcome_trigger(msg: str):
    if not msg:
        return False
    t = msg.strip().lower()
    return t in WELCOME_TRIGGERS

# ======================================================
# MAIN MESSAGE PROCESSOR
# ======================================================
def process_and_reply(data: dict):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            logger.info("No message in update")
            return

        chat_id = message["chat"]["id"]
        text = message.get("text") or message.get("caption", "") or ""
        message_id = message.get("message_id")

        logger.info("Processing chat_id=%s len=%d msg_id=%s", chat_id, len(text), message_id)

        # ———————————————
        # WELCOME MESSAGE
        # ———————————————
        if is_welcome_trigger(text) or message_id == 1:
            send_telegram_message(chat_id, WELCOME_TEXT)
            return

        # Acknowledge (optional)
        try:
            send_telegram_message(
                chat_id,
                "Memproses permintaan anda... Sila tunggu sebentar."
            )
        except:
            logger.exception("Failed ack send")

        # Empty text? stop
        if not text.strip():
            return

        # ———————————————
        # CALL OPENAI
        # ———————————————
        try:
            messages = build_openai_messages(text)
            reply = call_openai(messages)
        except Exception as e:
            logger.exception("OpenAI error: %s", e)
            send_telegram_message(chat_id, "Maaf, ralat perkhidmatan AI. Sila cuba lagi kemudian.")
            return

        # ———————————————
        # SPLIT LARGE MESSAGES
        # ———————————————
        MAX_LEN = 3900
        if len(reply) <= MAX_LEN:
            send_telegram_message(chat_id, reply)
        else:
            buffer = ""
            for p in reply.split("\n\n"):
                if len(buffer) + len(p) + 2 > MAX_LEN:
                    send_telegram_message(chat_id, buffer.strip())
                    buffer = p + "\n\n"
                else:
                    buffer += p + "\n\n"
            if buffer.strip():
                send_telegram_message(chat_id, buffer.strip())

    except Exception:
        logger.exception("process_and_reply crashed")

# ======================================================
# FASTAPI ROUTES
# ======================================================
@app.get("/")
async def root():
    return {"status": "Running ✔️", "model": OPENAI_MODEL, "temperature": OPENAI_TEMPERATURE}

@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    try:
        data = await request.json()
    except:
        logger.exception("Invalid JSON")
        return {"ok": True}

    background.add_task(process_and_reply, data)
    return {"ok": True}
