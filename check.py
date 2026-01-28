import cv2
import face_recognition
import pyodbc
import json
import numpy as np

# --- CONFIGURATION ---
SERVER_NAME = 'localhost'
DB_NAME = 'attendance_ai'
TOLERANCE = 0.6 

# --- DATABASE CONNECTION ---
def get_db_connection():
    return pyodbc.connect(
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={SERVER_NAME};'
        f'DATABASE={DB_NAME};'
        'Trusted_Connection=yes;'
    )

# --- LOGGING FUNCTION (No Time, Just Period) ---
def log_to_db(uid, name, subject, period, date_str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # We removed 'log_time' from this query
        sql = """
            INSERT INTO attendance_log 
            (student_uid, student_name, subject_name, period_number, log_date, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        values = (uid, name, subject, period, date_str, 'Present')
        
        cursor.execute(sql, values)
        conn.commit()
        conn.close()
        print(f" [DB] SUCCESS: Attendance saved for {name} (Period {period}).")
        
    except Exception as e:
        print(f" [DB] ERROR: Could not save log. {e}")

# --- MAIN SYSTEM ---
def run_attendance_system():
    # 1. GET SESSION DETAILS
    print("--- ATTENDANCE SESSION SETUP ---")
    subject = input("Enter Subject (e.g., Math): ")
    period  = input("Enter Period Number (e.g., 1): ")
    date_input = input("Enter Date (YYYY-MM-DD): ")
    
    # 2. LOAD ENCODINGS FROM DB
    print("\n--- LOADING DATABASE ---")
    known_encodings = []
    known_names = []
    known_uids = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT uid, name, encoding FROM face_data")
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            known_uids.append(row[0])
            known_names.append(row[1])
            known_encodings.append(np.array(json.loads(row[2])))
            
        print(f"Loaded {len(known_names)} students.")

    except Exception as e:
        print(f"Error loading DB: {e}")
        return

    # 3. CAPTURE IMAGE
    cam = cv2.VideoCapture(0)
    print("\n--- CAMERA ACTIVE: PRESS 'SPACE' TO MARK ATTENDANCE ---")
    
    original_frame = None

    while True:
        ret, frame = cam.read()
        if not ret: break
        
        # Display instructions on screen
        cv2.putText(frame, f"Subject: {subject} | Period: {period}", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        
        cv2.imshow("Attendance Scanner", frame)
        
        k = cv2.waitKey(1)
        if k % 256 == 32: # SPACE pressed
            original_frame = frame
            break
        elif k % 256 == 27: # ESC pressed
            cam.release()
            cv2.destroyAllWindows()
            return

    cam.release()
    cv2.destroyAllWindows()

    # 4. PROCESSING (Gray -> Detect -> Encode)
    print("Processing image...")
    gray_image = cv2.cvtColor(original_frame, cv2.COLOR_BGR2GRAY)
    face_locations = face_recognition.face_locations(gray_image)

    if not face_locations:
        print("❌ No face detected.")
        return

    rgb_image = cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)
    unknown_encodings = face_recognition.face_encodings(rgb_image, face_locations)
    
    if not unknown_encodings:
        print("❌ Could not encode face.")
        return

    target_encoding = unknown_encodings[0]

    # 5. COMPARE
    distances = face_recognition.face_distance(known_encodings, target_encoding)
    best_match_index = np.argmin(distances)
    best_distance = distances[best_match_index]

    if best_distance < TOLERANCE:
        # --- MATCH FOUND ---
        matched_uid = known_uids[best_match_index]
        matched_name = known_names[best_match_index]

        print("\n" + "="*40)
        print(f" ✅ MATCH CONFIRMED")
        print(f" Student: {matched_name}")
        print(f" UID:     {matched_uid}")
        print("="*40)

        # --- LOG TO DB (Without Time) ---
        log_to_db(matched_uid, matched_name, subject, period, date_input)

        # Draw Green Box
        top, right, bottom, left = face_locations[0]
        cv2.rectangle(original_frame, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.putText(original_frame, f"{matched_name} - PRESENT", (left, bottom + 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
    else:
        # --- NO MATCH ---
        print(f"\n❌ UNKNOWN STUDENT")
        top, right, bottom, left = face_locations[0]
        cv2.rectangle(original_frame, (left, top), (right, bottom), (0, 0, 255), 2)
        cv2.putText(original_frame, "UNKNOWN", (left, bottom + 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    # Show Final Result
    cv2.imshow("Final Result", original_frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_attendance_system()