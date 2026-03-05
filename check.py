import cv2 # OpenCV for webcam access 
import face_recognition # Face recognition library
import pyodbc 
import json # face encoding into json string
import numpy as np # for averaging face encodings
import time # for snapshot timing

SERVER_NAME = 'localhost'
DB_NAME = 'attendance_ai'

TOLERANCE = 0.45
SNAPSHOT_INTERVAL = 2
TOTAL_SNAPSHOTS = 6
PRESENT_THRESHOLD = 4

def get_db_connection():
    return pyodbc.connect(
        f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER_NAME};'
        f'DATABASE={DB_NAME};Trusted_Connection=yes;'
    )

def determine_status(snapshot_results):
    """
    Rules (checked in order):
      - Late Entry  : first 3 all False  AND at least 1 of last 3 True
      - Early Exit  : last 3 all False   AND at least 1 of first 3 True
      - Present     : 4 or more True
      - Absent      : everything else
    """
    first_half = snapshot_results[:3]   # snapshots 1-3
    last_half  = snapshot_results[3:]   # snapshots 4-6
    total_present = sum(snapshot_results)

    if not any(first_half) and any(last_half):
        return "LATE ENTRY"
    if not any(last_half) and any(first_half):
        return "EARLY EXIT"
    if total_present >= PRESENT_THRESHOLD:
        return "PRESENT"
    return "ABSENT"

# Check if attendance already exists
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

def run_class_session(class_name, subject, period, date_input):
    all_uids, all_names, all_encodings = get_students_by_class(class_name)
    if not all_uids:
        print("No students found for this class.")
        return

    # attendance_sheet[uid] = [False, False, False, False, False, False]
    attendance_sheet = {uid: [False] * TOTAL_SNAPSHOTS for uid in all_uids}
    uid_to_name = dict(zip(all_uids, all_names))

    cam = cv2.VideoCapture(0)

    for i in range(TOTAL_SNAPSHOTS):
        start_time = time.time()
        snapshot_taken = False

        while True:
            ret, frame = cam.read()
            if not ret:
                break

            elapsed   = time.time() - start_time
            time_left = int(SNAPSHOT_INTERVAL - elapsed)

            rgb_frame            = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_locations       = face_recognition.face_locations(rgb_frame)
            face_encodings_frame = face_recognition.face_encodings(rgb_frame, face_locations)

            for (top, right, bottom, left), face_enc in zip(face_locations, face_encodings_frame):
                name_to_display = "Unknown"
                box_color       = (0, 0, 255)

                if all_encodings:
                    distances       = face_recognition.face_distance(all_encodings, face_enc)
                    best_idx        = int(np.argmin(distances))

                    if distances[best_idx] <= TOLERANCE:
                        matched_uid     = all_uids[best_idx]
                        name_to_display = uid_to_name[matched_uid]
                        box_color       = (0, 255, 0)

                        # Mark attendance when the snapshot window closes
                        if elapsed >= SNAPSHOT_INTERVAL and not snapshot_taken:
                            attendance_sheet[matched_uid][i] = True

                cv2.rectangle(frame, (left, top), (right, bottom), box_color, 2)
                cv2.putText(
                    frame, name_to_display,
                    (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2
                )

            label = (
                f"Scanning {class_name} | "
                f"Photo {i + 1}/{TOTAL_SNAPSHOTS} | "
                f"Next in {max(0, time_left)}s"
            )
            cv2.putText(
                frame, label,
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
            )
            cv2.imshow("Teacher Desk Scanner", frame)
            cv2.waitKey(1)

            if elapsed >= SNAPSHOT_INTERVAL:
                snapshot_taken = True
                break

    cam.release()
    cv2.destroyAllWindows()

    # Evaluate and log every student
    for uid in all_uids:
        status = determine_status(attendance_sheet[uid])
        log_to_db(uid, uid_to_name[uid], class_name, subject, period, date_input, status)
        print(f"{uid_to_name[uid]}: {attendance_sheet[uid]} → {status}")