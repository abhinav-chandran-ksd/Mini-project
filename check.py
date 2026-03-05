import cv2 
import face_recognition 
import pyodbc 
import json 
import numpy as np 
import time 
import threading # Added for multi-threading

SERVER_NAME = 'localhost'
DB_NAME = 'attendance_ai'

TOLERANCE = 0.45
SNAPSHOT_INTERVAL = 2
TOTAL_SNAPSHOTS = 6
PRESENT_THRESHOLD = 4

# --- GLOBAL VARIABLES FOR THREAD SHARING ---
latest_frame = None
latest_detections = []
running = True

def get_db_connection():
    return pyodbc.connect(
        f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER_NAME};'
        f'DATABASE={DB_NAME};Trusted_Connection=yes;'
    )

def determine_status(snapshot_results):
    first_half = snapshot_results[:3]   
    last_half  = snapshot_results[3:]   
    total_present = sum(snapshot_results)

    if not any(first_half) and any(last_half):
        return "LATE ENTRY"
    if not any(last_half) and any(first_half):
        return "EARLY EXIT"
    if total_present >= PRESENT_THRESHOLD:
        return "PRESENT"
    return "ABSENT"

def log_to_db(uid, name, class_name, subject, period, date_str, status):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT log_id FROM attendance_log
            WHERE student_uid=? AND log_date=? AND period_number=? AND subject_name=?
        """, (uid, date_str, period, subject))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE attendance_log SET status=?, class_name=?, student_name=? WHERE log_id=?",
                (status, class_name, name, existing[0])
            )
        else:
            cursor.execute("""
                INSERT INTO attendance_log
                    (student_uid, student_name, class_name, subject_name, period_number, log_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (uid, name, class_name, subject, period, date_str, status))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"CRITICAL DB ERROR: {e}")

def get_students_by_class(target_class):
    known_encodings, known_names, known_uids = [], [], []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT uid, name, encoding FROM face_data WHERE class_name = ?",
            (target_class,)
        )
        for row in cursor.fetchall():
            known_uids.append(row[0])
            known_names.append(row[1])
            known_encodings.append(np.array(json.loads(row[2])))
        conn.close()
    except:
        pass
    return known_uids, known_names, known_encodings

# --- MODULE 1: AI Processing Thread ---
def process_faces_worker(all_uids, all_encodings, uid_to_name, attendance_sheet, start_time):
    global latest_frame, latest_detections, running

    while running:
        # Grab a copy of the latest frame safely
        if latest_frame is None:
            time.sleep(0.05)
            continue
        
        frame_to_process = latest_frame.copy()

        # Determine which snapshot window we are currently in
        elapsed = time.time() - start_time
        snapshot_idx = int(elapsed // SNAPSHOT_INTERVAL)

        if snapshot_idx >= TOTAL_SNAPSHOTS:
            break

        # Heavy AI Computation
        rgb_frame = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings_frame = face_recognition.face_encodings(rgb_frame, face_locations)

        current_detections = []

        for (top, right, bottom, left), face_enc in zip(face_locations, face_encodings_frame):
            name_to_display = "Unknown"
            box_color = (0, 0, 255)

            if all_encodings:
                distances = face_recognition.face_distance(all_encodings, face_enc)
                best_idx = int(np.argmin(distances))

                if distances[best_idx] <= TOLERANCE:
                    matched_uid = all_uids[best_idx]
                    name_to_display = uid_to_name[matched_uid]
                    box_color = (0, 255, 0)

                    # Mark them present for this specific snapshot window
                    if snapshot_idx < TOTAL_SNAPSHOTS:
                        attendance_sheet[matched_uid][snapshot_idx] = True

            # Save coordinates for the camera thread to draw
            current_detections.append((left, top, right, bottom, name_to_display, box_color))

        # Push the newest detections to the global variable
        latest_detections = current_detections

        # Tiny sleep to prevent locking up the CPU completely
        time.sleep(0.01)

# --- MODULE 2: Camera & Display (Main Thread) ---
def run_class_session(class_name, subject, period, date_input):
    global running, latest_frame, latest_detections
    
    # Reset globals for a new session
    running = True
    latest_frame = None
    latest_detections = []

    all_uids, all_names, all_encodings = get_students_by_class(class_name)
    if not all_uids:
        print("No students found for this class.")
        return

    attendance_sheet = {uid: [False] * TOTAL_SNAPSHOTS for uid in all_uids}
    uid_to_name = dict(zip(all_uids, all_names))

    # Start the camera
    cam = cv2.VideoCapture(0)
    start_time = time.time()

    # Launch the AI in a background thread
    ai_thread = threading.Thread(
        target=process_faces_worker, 
        args=(all_uids, all_encodings, uid_to_name, attendance_sheet, start_time)
    )
    ai_thread.start()

    while running:
        ret, frame = cam.read()
        if not ret:
            break

        # Send frame to the AI thread
        latest_frame = frame.copy()

        # Draw the most recent AI results
        for (left, top, right, bottom, name_to_display, box_color) in latest_detections:
            cv2.rectangle(frame, (left, top), (right, bottom), box_color, 2)
            cv2.putText(
                frame, name_to_display,
                (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2
            )

        # Calculate time
        elapsed = time.time() - start_time
        snapshot_idx = int(elapsed // SNAPSHOT_INTERVAL)
        time_left = SNAPSHOT_INTERVAL - (elapsed % SNAPSHOT_INTERVAL)

        if snapshot_idx >= TOTAL_SNAPSHOTS:
            running = False
            break

        # UI Text
        label = (
            f"Scanning {class_name} | "
            f"Photo {snapshot_idx + 1}/{TOTAL_SNAPSHOTS} | "
            f"Next in {int(time_left)}s"
        )
        cv2.putText(
            frame, label,
            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
        )

        cv2.imshow("Teacher Desk Scanner", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            running = False
            break

    # Cleanup
    cam.release()
    cv2.destroyAllWindows()
    ai_thread.join() # Wait for the background AI to safely finish

    # Evaluate and log every student
    for uid in all_uids:
        status = determine_status(attendance_sheet[uid])
        log_to_db(uid, uid_to_name[uid], class_name, subject, period, date_input, status)
        print(f"{uid_to_name[uid]}: {attendance_sheet[uid]} → {status}")