import sqlite3
import time
from datetime import datetime
import os

DB_NAME = "parking_history.db"

def init_db():
    """Initialize the SQLite database for history."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Create table for parking history
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  slot_id INTEGER,
                  entry_time TEXT,
                  exit_time TEXT,
                  duration_seconds INTEGER,
                  fee REAL)''')
    conn.commit()
    conn.close()

def log_entry(slot_id):
    """Logs a car entering a slot."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Only insert if there isn't an active session for this slot (exit_time is NULL)
    c.execute("SELECT id FROM history WHERE slot_id = ? AND exit_time IS NULL", (slot_id,))
    if c.fetchone() is None:
        c.execute("INSERT INTO history (slot_id, entry_time) VALUES (?, ?)", (slot_id, entry_time))
        conn.commit()
    conn.close()

def log_exit(slot_id, duration, fee):
    """Logs a car exiting and returns the Transaction ID."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Find the active session for this slot
    c.execute("SELECT id FROM history WHERE slot_id = ? AND exit_time IS NULL", (slot_id,))
    row = c.fetchone()
    
    log_id = None
    if row:
        log_id = row[0]
        c.execute("UPDATE history SET exit_time = ?, duration_seconds = ?, fee = ? WHERE id = ?", 
                  (exit_time, duration, fee, log_id))
        conn.commit()
    
    conn.close()
    return log_id

def fetch_history():
    """Returns the last 20 records for the dashboard."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM history ORDER BY id DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    
    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "slot_id": r[1],
            "entry_time": r[2],
            "exit_time": r[3],
            "duration_seconds": r[4],
            "final_fee": r[5]
        })
    return data

def fetch_all_history():
    """Returns all history for Excel download."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM history ORDER BY id ASC")
    rows = c.fetchall()
    conn.close()
    
    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "slot_id": r[1],
            "entry_time": r[2],
            "exit_time": r[3],
            "duration_seconds": r[4],
            "final_fee": r[5]
        })
    return data

def clear_all_history():
    """Manually clears the database."""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("DELETE FROM history")
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_daily_analysis():
    # Placeholder for simple analytics
    return {"message": "Daily analysis available in Excel report"}

def cleanup_old_records(seconds_threshold=10):
    """
    Deletes records from the database that were COMPLETED (Exited)
    more than 'seconds_threshold' ago.
    """
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # We need to fetch rows to check python-side time diff, 
        # or use SQL if we stored timestamps. Since we stored string "YYYY-MM-DD...",
        # it is safer to fetch and check in Python to avoid SQL complexity errors.
        
        c.execute("SELECT id, exit_time FROM history WHERE exit_time IS NOT NULL")
        rows = c.fetchall()
        
        ids_to_delete = []
        now = datetime.now()
        
        for row in rows:
            row_id = row[0]
            exit_str = row[1]
            try:
                exit_dt = datetime.strptime(exit_str, "%Y-%m-%d %H:%M:%S")
                # Calculate difference in seconds
                diff = (now - exit_dt).total_seconds()
                if diff > seconds_threshold:
                    ids_to_delete.append(row_id)
            except:
                pass

        if ids_to_delete:
            # Delete identified rows
            c.executemany("DELETE FROM history WHERE id = ?", [(x,) for x in ids_to_delete])
            conn.commit()
            print(f"cleaned up {len(ids_to_delete)} old history records.")
            
        conn.close()
    except Exception as e:
        print(f"DB Cleanup Error: {e}")



