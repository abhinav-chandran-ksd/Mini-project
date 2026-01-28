import face_recognition
import os
import numpy as np
import json
import pyodbc

# --- CONFIGURATION ---
FOLDER_PATH = "C:\\codes\\projects\\mini\\dataset\\u2303005"     # Folder containing your 10 images
MY_NAME = "Aswin"         # The name you want in the database
SERVER_NAME = 'localhost'   # Use 'localhost' or your computer name
DB_NAME = 'attendance_ai'        # Database name
UID='u2303005'            # Your unique ID

def enroll_face():
    print(f"--- STARTING ENROLLMENT FOR {MY_NAME} ---")
    
    all_encodings = []
    images = os.listdir(FOLDER_PATH)

    # 1. READ IMAGES & EXTRACT VECTORS
    for filename in images:
        path = os.path.join(FOLDER_PATH, filename)
        
        # Load image
        try:
            img = face_recognition.load_image_file(path)
            # Get encoding (128-d vector)
            encs = face_recognition.face_encodings(img)
            
            if len(encs) > 0:
                all_encodings.append(encs[0])
                print(f" [OK] Processed: {filename}")
            else:
                print(f" [SKIP] No face found: {filename}")
        except Exception as e:
            print(f" [ERROR] Could not read {filename}: {e}")

    if not all_encodings:
        print("Error: No valid faces found. Check your photos.")
        return

    # 2. AVERAGE THE VECTORS (The "Magic" Step)
    # 
    # We take the mean across axis 0 to get one stable vector
    master_vector = np.mean(all_encodings, axis=0)
    
    # Convert numpy array to JSON string for SQL storage
    vector_json = json.dumps(master_vector.tolist())
    
    # 3. SAVE TO SQL SERVER
    try:
        conn = pyodbc.connect(
            f'DRIVER={{ODBC Driver 17 for SQL Server}};'
            f'SERVER={SERVER_NAME};'
            f'DATABASE={DB_NAME};'
            'Trusted_Connection=yes;'
        )
        cursor = conn.cursor()
        
        # Check if user already exists
        cursor.execute("SELECT id FROM face_data WHERE name = ?", (MY_NAME,))
        data = cursor.fetchone()
        
        if data:
            # Update existing
            print("User already exists. Updating face data...")
            cursor.execute("UPDATE face_data SET encoding = ? WHERE name = ?", (vector_json, MY_NAME))
        else:
            # Insert new
            print("Creating new user...")
            cursor.execute("INSERT INTO face_data (name, encoding, uid) VALUES (?, ?, ?)", (MY_NAME, vector_json, UID))
        
        conn.commit()
        conn.close()
        
        print("------------------------------------------------")
        print(f"SUCCESS: {MY_NAME} has been saved to the database!")
        
    except pyodbc.Error as ex:
        print("SQL ERROR:", ex)
        print("Tip: Check if your Server Name is correct or if the DB exists.")

if __name__ == "__main__":
    enroll_face()