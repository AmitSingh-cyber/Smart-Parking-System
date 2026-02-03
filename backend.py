import cv2
import time
import numpy as np
import json
import os
import hashlib
import requests
import random
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Body, Response, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from ultralytics import YOLO
from shapely.geometry import Polygon, Point, box
import uvicorn
import shutil
from collections import defaultdict
import sys 
import pandas as pd 
from openpyxl.utils import get_column_letter
import asyncio
import barcode
from barcode.writer import ImageWriter

# IMPORT MODULES
import database 
import alerts 
import invoice_generator 

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "parking_database.json"
FIXED_WIDTH = 1000
FIXED_HEIGHT = 600

# --- CONFIGURATION ---
OWNER_ID = "admin"
OWNER_PASS = "admin123"
TELEGRAM_BOT_TOKEN = "8560761927:AAEJrohBEiFoXNbGjvAqRJpVzRgEwjNhYFg" 

database.init_db()

# Global State
state = {
    "source": None,
    "current_video_id": "default",
    "slots": [],
    "reserved_indices": [],
    "reservation_timers": {},
    "active_bookings": {}, 
    "slot_bookings": {},
    "slot_start_times": {},
    "previous_statuses": {}, 
    "overstay_threshold": 180,
    "hourly_rate": 5.0,        
    "stats": {"total": 0, "free": 0, "filled": 0, "wrong": 0, "revenue": 0.0, "detailed": []},
    "current_users": [] 
}

model = YOLO("yolov8n.pt")
VEHICLE_CLASSES = [2, 3, 5, 7] 

# --- HELPER: TELEGRAM SENDER ---
def send_telegram_booking(chat_id, booking_id, slot_id, name, car_no):
    try:
        msg = (f"✅ PARKING CONFIRMED!\n\n"
               f"👤 Name: {name}\n"
               f"🚗 Car: {car_no}\n"
               f"🅿️ Slot: {slot_id}\n"
               f"🆔 Ticket ID: {booking_id}\n\n"
               f"Please show this ID to the guard.")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg})
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- BACKGROUND CLEANUP TASK (UPDATED) ---
async def cleanup_system_task():
    """
    Robust background task to delete old files and DB records.
    Runs every 1 second to ensure instant cleanup.
    """
    while True:
        await asyncio.sleep(1) # Check every 1 second
        
        # 1. Clean Invoices & Barcodes
        folder = "invoices"
        if os.path.exists(folder):
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    # Check for PDF or PNG (Barcodes)
                    if filename.endswith(".pdf") or filename.endswith(".png"):
                        # Delete if older than 5 seconds
                        if time.time() - os.path.getctime(file_path) > 5: 
                            os.remove(file_path)
                            print(f"Deleted old file: {filename}")
                except Exception as e:
                    # If file is open/busy, skip it and try next time
                    # Do not crash the loop
                    pass
            
        # 2. Clean Database History
        try:
            database.cleanup_old_records(seconds_threshold=10)
        except Exception as e:
            print(f"DB Cleanup Error: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_system_task())

# --- PAGE ROUTES ---
@app.get("/")
def read_root(): return FileResponse("login.html")
@app.get("/owner_panel")
def get_owner_dashboard(): return FileResponse("owner_dashboard.html")
@app.get("/owner_bookings")
def get_owner_bookings_page(): return FileResponse("owner_bookings.html")
@app.get("/user_view")
def get_user_dashboard(): return FileResponse("user_dashboard.html")
@app.get("/booking_form")
def get_booking_page(): return FileResponse("booking.html")

@app.post("/login_attempt")
async def login_attempt(data: dict = Body(...)):
    role = data.get("role")
    if role == "owner":
        if data.get("username") == OWNER_ID and data.get("password") == OWNER_PASS:
            return {"success": True, "redirect": "/owner_panel"}
        else: return {"success": False, "message": "Invalid Owner Credentials"}
    elif role == "user":
        state["current_users"].append({"name": data.get("name"), "vehicle": data.get("vehicle"), "login_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"success": True, "redirect": "/user_view"}
    return {"success": False, "message": "Unknown Role"}

@app.post("/submit_booking")
async def submit_booking(data: dict = Body(...)):
    try:
        slot_id = int(data.get("slot_id"))
        idx = slot_id - 1
        name = data.get("name")
        car = data.get("car")
        mobile = data.get("mobile")

        if idx < 0 or idx >= len(state["slots"]): return {"success": False, "message": "Invalid Slot"}
        if idx in state["reserved_indices"]: return {"success": False, "message": "Slot already taken!"}

        booking_id = f"{random.randint(10000, 99999)}"
        
        if not os.path.exists("invoices"): os.makedirs("invoices")
        barcode_path = f"invoices/barcode_{booking_id}"
        code128 = barcode.get('code128', booking_id, writer=ImageWriter())
        code128.save(barcode_path)

        state["reserved_indices"].append(idx)
        state["reservation_timers"][idx] = time.time() + 900 
        
        booking_details = {
            "booking_id": booking_id,
            "slot_id": slot_id,
            "name": name,
            "car": car,
            "mobile": mobile,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Active"
        }
        state["active_bookings"][booking_id] = booking_details
        state["slot_bookings"][idx] = booking_id
        
        save_to_database(state["current_video_id"], state["slots"], state["reserved_indices"])

        if mobile and mobile.isdigit(): 
            send_telegram_booking(mobile, booking_id, slot_id, name, car)

        return {"success": True, "booking_id": booking_id, "barcode_url": f"/get_barcode/barcode_{booking_id}.png", "message": "Booking Successful!"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/get_barcode/{filename}")
def get_barcode_img(filename: str):
    path = f"invoices/{filename}"
    if os.path.exists(path): return FileResponse(path)
    return JSONResponse(status_code=404, content={"message": "Not found"})

@app.get("/get_all_bookings")
def get_all_bookings(): return list(state["active_bookings"].values())

@app.post("/verify_booking")
async def verify_booking(data: dict = Body(...)):
    b_id = data.get("booking_id")
    if b_id in state["active_bookings"]: return {"success": True, "data": state["active_bookings"][b_id]}
    return {"success": False, "message": "Invalid Booking ID"}

# --- CORE FUNCTIONS ---
def load_database():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                content = json.load(f)
                if isinstance(content, dict): return content
        except: pass
    return {}

def save_to_database(video_id, slots, reserved):
    db = load_database()
    db[video_id] = {"slots": slots, "reserved": reserved}
    with open(DB_FILE, "w") as f: json.dump(db, f)

def get_video_id(filename): return hashlib.md5(filename.encode()).hexdigest()

def calculate_overlap(slot_poly, car_box):
    x1, y1, x2, y2 = car_box
    car_poly = box(x1, y1, x2, y2)
    if not slot_poly.intersects(car_poly): return 0.0
    return slot_poly.intersection(car_poly).area / car_poly.area

def draw_stylish_label(img, text, x, y, bg_color=(50, 50, 50), text_color=(255, 255, 255)):
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = 0.6
    thickness = 1
    (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
    pad = 6
    x1, y1 = x - text_w // 2 - pad, y - text_h // 2 - pad
    x2, y2 = x + text_w // 2 + pad, y + text_h // 2 + pad
    cv2.rectangle(img, (x1+2, y1+2), (x2+2, y2+2), (0,0,0), -1) 
    cv2.rectangle(img, (x1, y1), (x2, y2), bg_color, -1) 
    cv2.rectangle(img, (x1, y1), (x2, y2), (200, 200, 200), 1) 
    cv2.putText(img, text, (x - text_w // 2, y + text_h // 2), font, scale, text_color, thickness, cv2.LINE_AA)

@app.get("/history")
def get_history_route(): return database.fetch_history()

@app.get("/daily_stats")
def get_daily_stats_route(): return database.get_daily_analysis()

@app.get("/download_invoice/{invoice_id}")
def download_invoice(invoice_id: int):
    filename = f"invoices/invoice_{invoice_id}.pdf"
    if os.path.exists(filename): return FileResponse(path=filename, filename=f"Receipt_{invoice_id}.pdf", media_type='application/pdf')
    return JSONResponse(status_code=404, content={"message": "Invoice not found"})

@app.delete("/clear_history")
def clear_history_route():
    success = database.clear_all_history()
    return {"message": "Database cleared", "success": success}

@app.get("/download_excel")
def download_excel():
    data = database.fetch_all_history()
    if not data: df = pd.DataFrame(columns=["ID", "Slot Number", "Entry Time", "Exit Time", "Duration (Sec)", "Fee ($)"])
    else:
        df = pd.DataFrame(data)
        df.rename(columns={"id": "ID", "slot_id": "Slot Number", "entry_time": "Entry Time", "exit_time": "Exit Time", "duration_seconds": "Duration (Sec)", "final_fee": "Fee ($)"}, inplace=True)
    filename = "parking_report.xlsx"
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
        worksheet = writer.sheets['Sheet1']
        for i, column in enumerate(df.columns):
            max_len = max(df[column].astype(str).map(len).max() if not df[column].empty else 0, len(column))
            worksheet.column_dimensions[get_column_letter(i + 1)].width = max_len + 5
    return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.get("/first_frame")
def get_first_frame():
    if state["source"] is None: return JSONResponse(status_code=400, content={"message": "No source selected"})
    cap = cv2.VideoCapture(state["source"])
    if not cap.isOpened(): return JSONResponse(status_code=500, content={"message": "Cannot open video"})
    ret, frame = cap.read(); cap.release()
    if ret:
        frame = cv2.resize(frame, (FIXED_WIDTH, FIXED_HEIGHT))
        _, buffer = cv2.imencode(".jpg", frame)
        return Response(content=buffer.tobytes(), media_type="image/jpeg")
    return JSONResponse(status_code=500, content={"message": "Could not read frame"})

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    state["source"] = file_location; state["current_video_id"] = get_video_id(file.filename)
    db = load_database(); data = db.get(state["current_video_id"], {})
    if isinstance(data, list): state["slots"] = data; state["reserved_indices"] = []
    else: state["slots"] = data.get("slots", []); state["reserved_indices"] = data.get("reserved", [])
    state["slot_start_times"] = {}; state["previous_statuses"] = {} 
    return {"message": "Video uploaded", "has_saved_slots": len(state["slots"]) > 0}

@app.post("/use_camera")
async def use_camera():
    state["source"] = 0; state["current_video_id"] = "live_camera"
    db = load_database(); data = db.get("live_camera", {})
    if isinstance(data, list): state["slots"] = data; state["reserved_indices"] = []
    else: state["slots"] = data.get("slots", []); state["reserved_indices"] = data.get("reserved", [])
    state["slot_start_times"] = {}; state["previous_statuses"] = {}
    return {"message": "Camera active", "has_saved_slots": len(state["slots"]) > 0}

@app.post("/update_threshold")
async def update_threshold(seconds: int = Body(..., embed=True)): state["overstay_threshold"] = seconds; return {"message": "Updated"}
@app.post("/update_rate")
async def update_rate(rate: float = Body(..., embed=True)): state["hourly_rate"] = rate; return {"message": "Updated"}

@app.post("/toggle_reserved")
async def toggle_reserved(coords: dict = Body(...)):
    x, y = coords["x"], coords["y"]; point = Point(x, y)
    for i, slot in enumerate(state["slots"]):
        poly = Polygon(slot)
        if poly.contains(point):
            if i in state["reserved_indices"]: 
                state["reserved_indices"].remove(i)
                state["reservation_timers"].pop(i, None)
                msg = f"Slot {i+1} un-reserved"
            else: 
                state["reserved_indices"].append(i) 
                msg = f"Slot {i+1} marked as RESERVED"
            save_to_database(state["current_video_id"], state["slots"], state["reserved_indices"])
            return {"message": msg, "success": True}
    return {"message": "No slot found here", "success": False}

@app.get("/get_saved_slots")
def get_saved_slots(): return {"slots": state["slots"], "reserved": state["reserved_indices"]}

@app.post("/set_slots")
async def set_slots(data: dict):
    state["slots"] = data["slots"]
    if "reserved" in data: state["reserved_indices"] = data["reserved"]
    save_to_database(state["current_video_id"], state["slots"], state["reserved_indices"])
    return {"message": "Saved"}

@app.get("/stats")
def get_stats(): return state["stats"]

def process_video_stream():
    if state["source"] is None: return
    cap = cv2.VideoCapture(state["source"])
    if not cap.isOpened(): return
    fps = cap.get(cv2.CAP_PROP_FPS); fps = 30 if fps <= 0 else fps
    start_real_time = time.time()

    try:
        while cap.isOpened():
            now = time.time()
            expired_indices = [idx for idx, expiry in state["reservation_timers"].items() if now > expiry]
            for idx in expired_indices:
                if idx in state["reserved_indices"]: state["reserved_indices"].remove(idx)
                if idx in state["slot_bookings"]: del state["slot_bookings"][idx]
                del state["reservation_timers"][idx]
            
            if isinstance(state["source"], str):
                elapsed = time.time() - start_real_time
                target_frame = int(elapsed * fps)
                if target_frame > cap.get(cv2.CAP_PROP_POS_FRAMES): cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            ret, frame = cap.read()
            if not ret:
                if isinstance(state["source"], str): cap.set(cv2.CAP_PROP_POS_FRAMES, 0); start_real_time = time.time(); continue
                else: break

            frame = cv2.resize(frame, (FIXED_WIDTH, FIXED_HEIGHT))
            try: results = model(frame, verbose=False, conf=0.25, classes=VEHICLE_CLASSES)[0]; detected_cars = results.boxes.xyxy.cpu().numpy()
            except: detected_cars = []

            polygons = [Polygon(slot) for slot in state["slots"]]
            car_interactions = defaultdict(list)
            for car_idx, car_box in enumerate(detected_cars):
                for slot_idx, poly in enumerate(polygons):
                    overlap = calculate_overlap(poly, car_box)
                    if overlap > 0.15: car_interactions[car_idx].append((slot_idx, overlap))

            slots_status = {}
            for car_idx, interactions in car_interactions.items():
                if len(interactions) == 1:
                    slot_idx, overlap = interactions[0]
                    if overlap > 0.25: slots_status[slot_idx] = "FILLED"
                elif len(interactions) >= 2:
                    for slot_idx, _ in interactions: slots_status[slot_idx] = "WRONG"

            detailed_list = []
            current_now = time.time()
            current_revenue = 0.0

            for i in range(len(polygons)):
                status = slots_status.get(i, "FREE")
                is_reserved = i in state["reserved_indices"]
                prev_status = state["previous_statuses"].get(i, "FREE")
                
                if prev_status == "FREE" and (status == "FILLED" or status == "WRONG"): 
                    database.log_entry(i + 1)
                
                fee = 0.0; duration = 0
                if status in ["FILLED", "WRONG"]:
                    if i not in state["slot_start_times"]: state["slot_start_times"][i] = current_now
                    duration = int(current_now - state["slot_start_times"][i])
                    fee = (duration / 3600.0) * state["hourly_rate"]
                    current_revenue += fee
                else:
                    if prev_status in ["FILLED", "WRONG"]:
                        if i in state["slot_start_times"]:
                            start_ts = state["slot_start_times"][i]
                            final_duration = int(current_now - start_ts)
                            final_fee = (final_duration / 3600.0) * state["hourly_rate"]
                            log_id = database.log_exit(i + 1, final_duration, final_fee)
                            if log_id:
                                try:
                                    entry_dt = datetime.fromtimestamp(start_ts)
                                    exit_dt = datetime.fromtimestamp(current_now)
                                    invoice_generator.create_invoice(log_id, i+1, entry_dt, exit_dt, final_duration, final_fee)
                                except: pass
                            state["slot_start_times"].pop(i, None)
                    duration = 0

                state["previous_statuses"][i] = status
                is_overstay = duration > state["overstay_threshold"]
                
                reserved_remaining = 0
                if i in state["reservation_timers"]:
                    reserved_remaining = max(0, int(state["reservation_timers"][i] - current_now))
                
                detailed_list.append({
                    "id": i + 1, "status": status, "duration": duration, "fee": round(fee, 2), 
                    "is_overstay": is_overstay, "is_reserved": is_reserved,
                    "reserved_remaining": reserved_remaining
                })

            alerts.process_alerts(detailed_list)
            state["stats"] = {"total": len(polygons), "free": len(polygons) - sum(1 for s in slots_status.values() if s in ["FILLED", "WRONG"]), "filled": sum(1 for s in slots_status.values() if s == "FILLED"), "wrong": sum(1 for s in slots_status.values() if s == "WRONG"), "revenue": round(current_revenue, 2), "detailed": detailed_list}

            for i, slot in enumerate(state["slots"]):
                status = slots_status.get(i, "FREE")
                is_reserved = i in state["reserved_indices"]
                is_overstay = False
                if i < len(detailed_list): is_overstay = detailed_list[i]["is_overstay"]
                if status == "WRONG": color = (0, 255, 255)
                elif status == "FILLED": color = (255, 0, 255) if is_reserved else (0, 0, 255)
                else: color = (255, 0, 0) if is_reserved else (0, 255, 0)
                pts = np.array(slot, np.int32).reshape((-1, 1, 2))
                cv2.polylines(frame, [pts], True, color, 2)
                overlay = frame.copy(); cv2.fillPoly(overlay, [pts], color); frame = cv2.addWeighted(overlay, 0.3, frame, 0.7, 0)
                M = cv2.moments(pts)
                if M["m00"] != 0:
                    cX, cY = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
                    label_bg = (50, 50, 50)
                    if status == "WRONG": label_bg = (0, 200, 200)
                    elif is_overstay: label_bg = (0, 0, 200)
                    elif is_reserved: label_bg = (200, 0, 0)
                    draw_stylish_label(frame, f"S{i+1}", cX, cY, bg_color=label_bg)

            _, buffer = cv2.imencode(".jpg", frame)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
    except asyncio.CancelledError: print("Stream cancelled")
    except GeneratorExit: print("Stream stopped")

@app.get("/video_feed")
def video_feed(): return StreamingResponse(process_video_stream(), media_type="multipart/x-mixed-replace; boundary=frame")



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)



