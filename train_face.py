import face_recognition
import os
import json
import pyodbc
import numpy as np

SERVER_NAME = 'localhost' 
DB_NAME = 'attendance_ai' 

def enroll_face(folder_path, my_name, uid, class_name):
    print(f"--- STARTING ENROLLMENT FOR {my_name} ({class_name}) ---")
    
    if not os.path.exists(folder_path):
        return f"Error: Folder '{folder_path}' does not exist!"

    images = os.listdir(folder_path)
    all_encodings = []

    # Loop through ALL images and collect every valid face encoding
    for filename in images:
        path = os.path.join(folder_path, filename)
        try:
            img = face_recognition.load_image_file(path)
            encs = face_recognition.face_encodings(img)
            # Only use images where exactly ONE face is clearly visible
            if len(encs) == 1: 
                all_encodings.append(encs[0])
        except Exception as e:
            pass

    if not all_encodings:
        return "Error: Could not find any clear faces in the provided folder."

    # Calculate the mean (average) of all collected face encodings
    best_encoding = np.mean(all_encodings, axis=0)
    
    # Serialize the averaged array into JSON
    vector_json = json.dumps(best_encoding.tolist())

    try:
        conn = pyodbc.connect(f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER_NAME};DATABASE={DB_NAME};Trusted_Connection=yes;')
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM face_data WHERE uid = ?", (uid,))
        if cursor.fetchone():
            cursor.execute("UPDATE face_data SET encoding=?, name=?, class_name=? WHERE uid=?", (vector_json, my_name, class_name, uid))
            msg = "Updated existing student profile with averaged face data!"
        else:
            cursor.execute("INSERT INTO face_data (name, encoding, uid, class_name) VALUES (?, ?, ?, ?)", (my_name, vector_json, uid, class_name))
            msg = "New student enrolled successfully!"
            
        conn.commit()
        conn.close()
        return f"SUCCESS: {my_name} saved. {msg}"
    except Exception as ex:
        return f"SQL ERROR: {ex}"