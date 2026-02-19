import cv2
import face_recognition
import pyodbc
import json
import numpy as np
import time

SERVER_NAME = 'localhost'
DB_NAME = 'attendance_ai'

TOLERANCE = 0.45         
SNAPSHOT_INTERVAL = 2    
TOTAL_SNAPSHOTS = 5      
PASSING_THRESHOLD = 2    

def get_db_connection():
    return pyodbc.connect(f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER_NAME};DATABASE={DB_NAME};Trusted_Connection=yes;')

def log_to_db(uid, name, class_name, subject, period, date_str, status, notes=""):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        final_status = f"{status} ({notes})" if notes else status
        
        cursor.execute("""
            SELECT log_id FROM attendance_log 
            WHERE student_uid=? AND log_date=? AND period_number=? AND subject_name=?
        """, (uid, date_str, period, subject))
        
        existing_record = cursor.fetchone()
        
        if existing_record:
            cursor.execute("UPDATE attendance_log SET status=?, class_name=?, student_name=? WHERE log_id=?", 
                           (final_status, class_name, name, existing_record[0]))
        else:
            cursor.execute("""
                INSERT INTO attendance_log (student_uid, student_name, class_name, subject_name, period_number, log_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (uid, name, class_name, subject, period, date_str, final_status))
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"CRITICAL DB ERROR: {e}")

def get_students_by_class(target_class):
    known_encodings, known_names, known_uids = [], [], []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT uid, name, encoding FROM face_data WHERE class_name = ?", (target_class,))
        for row in cursor.fetchall():
            known_uids.append(row[0])
            known_names.append(row[1])
            known_encodings.append(np.array(json.loads(row[2])))
        conn.close()
    except: pass
    return known_uids, known_names, known_encodings

def run_class_session(class_name, subject, period, date_input):
    all_uids, all_names, all_encodings = get_students_by_class(class_name)
    if not all_uids: return
        
    attendance_sheet = {uid: [False]*TOTAL_SNAPSHOTS for uid in all_uids}
    uid_to_name = {uid: name for uid, name in zip(all_uids, all_names)}

    cam = cv2.VideoCapture(0)
    for i in range(TOTAL_SNAPSHOTS):
        start_time = time.time()
        
        while True:
            ret, frame = cam.read()
            if not ret: break
            time_left = int((start_time + SNAPSHOT_INTERVAL) - time.time())
            
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_frame)
            face_encodings_in_frame = face_recognition.face_encodings(rgb_frame, face_locations)

            for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings_in_frame):
                matches = face_recognition.compare_faces(all_encodings, face_encoding, tolerance=TOLERANCE)
                face_distances = face_recognition.face_distance(all_encodings, face_encoding)
                
                name_to_display = "Unknown"
                box_color = (0, 0, 255) 
                
                if len(face_distances) > 0:
                    best_match_index = np.argmin(face_distances)
                    if face_distances[best_match_index] <= TOLERANCE:
                        matched_uid = all_uids[best_match_index]
                        name_to_display = uid_to_name[matched_uid]
                        box_color = (0, 255, 0) 
                        
                        if time_left <= 0:
                            attendance_sheet[matched_uid][i] = True

                cv2.rectangle(frame, (left, top), (right, bottom), box_color, 2)
                cv2.putText(frame, name_to_display, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2)

            cv2.putText(frame, f"Scanning {class_name} | Photo {i+1}/{TOTAL_SNAPSHOTS} in {max(0, time_left)}s", 
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Teacher Desk Scanner", frame)
            cv2.waitKey(1)
            
            if time_left <= 0: break 
    
    cam.release()
    cv2.destroyAllWindows()

    for uid in all_uids:
        present_count = sum(attendance_sheet[uid])
        name = uid_to_name[uid]
        status, notes = "ABSENT", ""

        if present_count < PASSING_THRESHOLD:
            if present_count > 0: notes = "Low Accuracy"
        else:
            status = "PRESENT"

        log_to_db(uid, name, class_name, subject, period, date_input, status, notes)