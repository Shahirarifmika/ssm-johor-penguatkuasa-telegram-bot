import os
import logging
import requests
from fastapi import FastAPI, Request, BackgroundTasks
import openai

# -------------------------
# Config & Logging
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ssm_bot")

# Environment variables (set these in Railway Variables)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # change if needed

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.error("Missing TELEGRAM_BOT_TOKEN or OPENAI_API_KEY in environment")
    # Exit early so Railway shows fail logs instead of continuing broken service
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and OPENAI_API_KEY in environment variables")

openai.api_key = OPENAI_API_KEY
TG_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI()

# -------------------------
# Load system instruction
# -------------------------
SYSTEM_INSTRUCTION = ""
try:
    with open("instructions.txt", "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read()
        logger.info("Loaded instructions.txt (length=%d)", len(SYSTEM_INSTRUCTION))
except Exception:
    logger.warning("instructions.txt not found or unreadable; using fallback instruction.")
    SYSTEM_INSTRUCTION = "Anda ialah Penguatkuasa SSM Johor. Jawab mengikut arahan."

# -------------------------
# Helper: Telegram send
# -------------------------
def send_telegram_message(chat_id: int, text: str):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        # use a (connect, read) tuple for timeout to reduce chance of blocking
        resp = requests.post(f"{TG_API_URL}/sendMessage", json=payload, timeout=(5, 15))
        if not resp.ok:
            logger.error("Telegram sendMessage failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Error sending telegram message: %s", e)

# -------------------------
# OpenAI helpers
# -------------------------
def build_openai_messages(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_text}
    ]

def call_openai(messages):
    """
    Calls OpenAI ChatCompletion with a timeout to avoid long blocking.
    Raises exception on failure (caller should handle).
    """
    try:
        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.0,
            max_tokens=600,         # conservative default for testing
            request_timeout=30      # seconds
        )
        return resp.choices[0].message["content"]
    except Exception as e:
        logger.exception("OpenAI API error: %s", e)
        raise

# -------------------------
# Background processor
# -------------------------
def process_and_reply(data: dict):
    try:
        if not isinstance(data, dict):
            logger.warning("Background: data not dict")
            return

        message = data.get("message") or data.get("edited_message")
        if not message:
            logger.info("Background: no message field")
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        logger.info("Background processing chat_id=%s message_id=%s", chat_id, message_id)

        if chat_id is None:
            logger.warning("Background: missing chat_id")
            return

        text = message.get("text", "") or message.get("caption", "")

        # 1) Initial ack (background)
        try:
            send_telegram_message(chat_id, "Memproses permintaan anda... Sila tunggu sebentar.")
        except Exception:
            # error logged in send_telegram_message
            pass

        # 2) Build messages and call OpenAI
        try:
            messages = build_openai_messages(text)
            reply = call_openai(messages)
        except Exception as e:
            logger.exception("OpenAI call failed for chat_id=%s: %s", chat_id, e)
            try:
                send_telegram_message(chat_id, "Maaf, berlaku ralat pada perkhidmatan AI. Sila cuba lagi kemudian.")
            except Exception:
                pass
            return

        # 3) Send reply (split if too long)
        try:
            MAX_LEN = 4000
            if not reply:
                send_telegram_message(chat_id, "Maaf, tiada jawapan diterima daripada perkhidmatan AI.")
                return

            if len(reply) <= MAX_LEN:
                send_telegram_message(chat_id, reply)
            else:
                # Smart split by paragraphs to avoid chopping sentences
                parts = reply.split("\n\n")
                buffer = ""
                for p in parts:
                    if len(buffer) + len(p) + 2 > MAX_LEN:
                        send_telegram_message(chat_id, buffer.strip())
                        buffer = p + "\n\n"
                    else:
                        buffer += p + "\n\n"
                if buffer.strip():
                    send_telegram_message(chat_id, buffer.strip())
        except Exception as e:
            logger.exception("Failed to send reply for chat_id=%s: %s", chat_id, e)
            try:
                send_telegram_message(chat_id, "Maaf, tidak dapat menghantar jawapan penuh. Sila hubungi pejabat SSM.")
            except Exception:
                pass

    except Exception as e:
        logger.exception("Unhandled error in background processor: %s", e)

# -------------------------
# Webhook endpoint - ACK cepat
# -------------------------
@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    """
    ACK cepat: parse JSON (safely), queue background task and RETURN 200 immediately.
    All heavy work is in process_and_reply (background).
    """
    try:
        data = await request.json()
    except Exception as e:
        logger.exception("Invalid JSON from Telegram: %s", e)
        # Return 200 so Telegram stops retrying bad payloads
        return {"ok": True}

    # Minimal logging to help debug
    try:
        logger.info("Received webhook (queued). keys=%s", list(data.keys()))
    except Exception:
        pass

    # Queue background work
    try:
        background.add_task(process_and_reply, data)
    except Exception as e:
        logger.exception("Failed to schedule background task: %s", e)
        # still return 200 to avoid Telegram retries

    return {"ok": True}

# -------------------------
# Health endpoint
# -------------------------
@app.get("/_health")
def health():
    return {"ok": True, "service": "ssm_bot"}
