import time
import requests
import threading

# ==========================================
# 👇 CONFIGURE YOUR TELEGRAM DETAILS HERE 👇
# ==========================================
# Your credentials are set correctly below:
TELEGRAM_BOT_TOKEN = "8560761927:AAEJrohBEiFoXNbGjvAqRJpVzRgEwjNhYFg" 
TELEGRAM_CHAT_ID = "1935821849"
# ==========================================

# State Management
alert_cooldowns = {}
COOLDOWN_SECONDS = 60  # Prevent spamming the same alert (1 min cooldown)

def send_telegram_message(message):
    """Sends a message to the configured Telegram user in a background thread."""
    
    # 1. Check if tokens are still placeholders (This logic is fine)
    if "YOUR_BOT_TOKEN" in TELEGRAM_BOT_TOKEN or "YOUR_CHAT_ID" in TELEGRAM_CHAT_ID:
        print(f"❌ TELEGRAM CONFIG ERROR: Please update 'alerts.py' with your Bot Token and Chat ID to send: '{message}'")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    def request_task():
        try:
            # 2. Send Request with a timeout
            response = requests.post(url, data=payload, timeout=10)
            
            # 3. Check for success
            if response.status_code == 200:
                print(f"✅ Telegram Alert Sent: {message}")
            else:
                print(f"⚠️ Telegram Failed (Status {response.status_code}): {response.text}")
                
        except Exception as e:
            print(f"⚠️ Telegram Connection Error: {e}")

    # Run in a daemon thread so it doesn't block the video or stop shutdown
    threading.Thread(target=request_task, daemon=True).start()

def process_alerts(detailed_slots):
    """
    Analyzes the current slots and determines if an alert is needed.
    """
    global alert_cooldowns
    current_time = time.time()

    for slot in detailed_slots:
        slot_id = slot["id"]
        status = slot["status"]
        is_overstay = slot["is_overstay"]
        
        # --- ALERT 1: WRONG PARKING ---
        if status == "WRONG":
            alert_key = f"{slot_id}_WRONG"
            last_sent = alert_cooldowns.get(alert_key, 0)
            
            # Check Cooldown
            if current_time - last_sent > COOLDOWN_SECONDS:
                msg = f"⚠️ SECURITY ALERT: Car in Slot {slot_id} is parked INCORRECTLY (Taking 2 spaces)!"
                send_telegram_message(msg)
                alert_cooldowns[alert_key] = current_time

        # --- ALERT 2: OVERSTAY ---
        if is_overstay:
            alert_key = f"{slot_id}_OVERSTAY"
            last_sent = alert_cooldowns.get(alert_key, 0)
            
            # Check Cooldown
            if current_time - last_sent > COOLDOWN_SECONDS:
                msg = f"⏳ OVERSTAY ALERT: Slot {slot_id} has exceeded the time limit! Fee is currently ${slot['fee']}."
                send_telegram_message(msg)
                alert_cooldowns[alert_key] = current_time
