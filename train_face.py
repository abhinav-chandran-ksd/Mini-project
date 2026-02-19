import face_recognition
import os
import json
import pyodbc

SERVER_NAME = 'localhost' 
DB_NAME = 'attendance_ai' 

def enroll_face(folder_path, my_name, uid, class_name):
    print(f"--- STARTING ENROLLMENT FOR {my_name} ({class_name}) ---")
    
    if not os.path.exists(folder_path):
        return f"Error: Folder '{folder_path}' does not exist!"

    images = os.listdir(folder_path)
    best_encoding = None

    for filename in images:
        path = os.path.join(folder_path, filename)
        try:
            img = face_recognition.load_image_file(path)
            encs = face_recognition.face_encodings(img)
            if len(encs) == 1: 
                best_encoding = encs[0]
                break 
        except Exception as e:
            pass

    if best_encoding is None:
        return "Error: Could not find a clear, single face in the provided folder."

    vector_json = json.dumps(best_encoding.tolist())

    try:
        conn = pyodbc.connect(f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER_NAME};DATABASE={DB_NAME};Trusted_Connection=yes;')
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM face_data WHERE uid = ?", (uid,))
        if cursor.fetchone():
            cursor.execute("UPDATE face_data SET encoding=?, name=?, class_name=? WHERE uid=?", (vector_json, my_name, class_name, uid))
            msg = "Updated existing student profile with sharper face data!"
        else:
            cursor.execute("INSERT INTO face_data (name, encoding, uid, class_name) VALUES (?, ?, ?, ?)", (my_name, vector_json, uid, class_name))
            msg = "New student enrolled successfully!"
            
        conn.commit()
        conn.close()
        return f"SUCCESS: {my_name} saved. {msg}"
    except Exception as ex:
        return f"SQL ERROR: {ex}"