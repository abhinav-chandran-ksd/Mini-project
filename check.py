import cv2
import face_recognition
import pyodbc
import json
import numpy as np
import time
from multiprocessing import Process, Queue, Event

SERVER_NAME = 'localhost'
DB_NAME = 'attendance_ai'

# --- DEMO TUNING PARAMETERS ---
TOLERANCE = 0.48
SNAPSHOT_INTERVAL = 10
TOTAL_SNAPSHOTS = 6
PRESENT_THRESHOLD = 4

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
    except Exception as e:
        print(f"Error loading students: {e}")
    return known_uids, known_names, known_encodings

# =====================================================================
# MODULE 1: INDEPENDENT AI PROCESS (Runs on a separate CPU core)
# =====================================================================
def ai_worker_process(input_queue, output_queue, stop_event, all_uids, all_encodings, uid_to_name, start_time):
    # This loop runs completely isolated from the camera
    while not stop_event.is_set():
        if not input_queue.empty():
            # Get the latest frame from the mailbox
            frame_data = input_queue.get()
            frame_to_process = frame_data['frame']
            snapshot_idx = frame_data['snapshot_idx']

            rgb_frame = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=2)
            face_encodings_frame = face_recognition.face_encodings(rgb_frame, face_locations)

            current_detections = []
            present_uids_this_frame = []

            for (top, right, bottom, left), face_enc in zip(face_locations, face_encodings_frame):
                name_to_display = "Unknown"
                box_color = (0, 0, 255)
                matched_uid = None

                if all_encodings:
                    distances = face_recognition.face_distance(all_encodings, face_enc)
                    best_idx = int(np.argmin(distances))

                    if distances[best_idx] <= TOLERANCE:
                        matched_uid = all_uids[best_idx]
                        name_to_display = uid_to_name[matched_uid]
                        box_color = (0, 255, 0)
                        present_uids_this_frame.append(matched_uid)

                current_detections.append((left, top, right, bottom, name_to_display, box_color))

            # Put the results in the outgoing mailbox for the camera to draw
            if output_queue.empty():
                output_queue.put({
                    'detections': current_detections,
                    'present_uids': present_uids_this_frame,
                    'snapshot_idx': snapshot_idx
                })
        else:
            time.sleep(0.01) # Rest the CPU if mailbox is empty

# =====================================================================
# MODULE 2: CAMERA & UI PROCESS (Main Loop)
# =====================================================================
def run_class_session(class_name, subject, period, date_input):
    all_uids, all_names, all_encodings = get_students_by_class(class_name)
    if not all_uids:
        print("No students found for this class.")
        return

    attendance_sheet = {uid: [False] * TOTAL_SNAPSHOTS for uid in all_uids}
    uid_to_name = dict(zip(all_uids, all_names))

    # Create the Mailboxes (Queues) and the Stop Signal
    input_queue = Queue(maxsize=1)
    output_queue = Queue(maxsize=1)
    stop_event = Event()

    start_time = time.time()

    # Launch the AI module as an independent process
    ai_process = Process(
        target=ai_worker_process,
        args=(input_queue, output_queue, stop_event, all_uids, all_encodings, uid_to_name, start_time)
    )
    ai_process.start()

    cam = cv2.VideoCapture(0)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    latest_detections = []
    
    while True:
        ret, frame = cam.read()
        if not ret:
            break

        elapsed = time.time() - start_time
        snapshot_idx = int(elapsed // SNAPSHOT_INTERVAL)
        time_left = SNAPSHOT_INTERVAL - (elapsed % SNAPSHOT_INTERVAL)

        if snapshot_idx >= TOTAL_SNAPSHOTS:
            break

        # Send a copy of the frame to the AI ONLY if it has finished the last one
        if input_queue.empty():
            input_queue.put({'frame': frame.copy(), 'snapshot_idx': snapshot_idx})

        # Check if the AI has sent back any new bounding boxes
        if not output_queue.empty():
            ai_results = output_queue.get()
            latest_detections = ai_results['detections']
            
            # Mark attendance based on AI results
            for uid in ai_results['present_uids']:
                if ai_results['snapshot_idx'] < TOTAL_SNAPSHOTS:
                    attendance_sheet[uid][ai_results['snapshot_idx']] = True

        # Draw the latest known bounding boxes instantly (no lag)
        for (left, top, right, bottom, name_to_display, box_color) in latest_detections:
            cv2.rectangle(frame, (left, top), (right, bottom), box_color, 3)
            cv2.rectangle(frame, (left, top - 35), (right, top), box_color, cv2.FILLED)
            cv2.putText(frame, name_to_display, (left + 6, top - 6), cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), 1)

        # UI Text
        label = f"Scanning: {class_name} | Photo {snapshot_idx + 1}/{TOTAL_SNAPSHOTS} | Next scan in {int(time_left)}s"
        cv2.rectangle(frame, (10, 10), (700, 60), (0, 0, 0), cv2.FILLED)
        cv2.putText(frame, label, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        cv2.imshow("Teacher Desk Scanner - LIVE DEMO", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Cleanup properly
    stop_event.set()
    cam.release()
    cv2.destroyAllWindows()
    ai_process.join()

    print("\n--- ATTENDANCE RESULTS ---")
    for uid in all_uids:
        status = determine_status(attendance_sheet[uid])
        log_to_db(uid, uid_to_name[uid], class_name, subject, period, date_input, status)
        print(f"{uid_to_name[uid]}: {attendance_sheet[uid]} → {status}")
    print("--------------------------\n")