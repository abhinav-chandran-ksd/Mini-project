from flask import Flask, render_template, request, session, redirect
import pyodbc
import check
import train_face

app = Flask(__name__)
app.secret_key = 'super_secret_key' 

def get_db():
    return pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=attendance_ai;Trusted_Connection=yes;')

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id, role FROM users WHERE username=? AND password=?", (username, password))
        user_auth = cursor.fetchone()
        
        if user_auth:
            user_id = user_auth[0]
            role = user_auth[1]
            
            session['username'] = username
            session['role'] = role
            
            if role == 'Admin':
                conn.close()
                return redirect('/admin')
                
            elif role == 'Teacher':
                cursor.execute("SELECT class_teacher_of, subject_teacher_of FROM teachers WHERE user_id=?", (user_id,))
                teacher_data = cursor.fetchone()
                if teacher_data:
                    session['class_teacher_of'] = teacher_data[0]
                    session['subject_teacher_of'] = teacher_data[1]
                conn.close()
                return redirect('/teacher_hub')
                
            elif role == 'Student':
                cursor.execute("SELECT uid, class_name FROM students WHERE user_id=?", (user_id,))
                student_data = cursor.fetchone()
                if student_data:
                    session['uid'] = student_data[0]
                    session['class_name'] = student_data[1]
                conn.close()
                return redirect('/student')
                
        else:
            error = "Invalid Credentials!"
            conn.close()
            
    return render_template('login.html', error=error)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if session.get('role') != 'Admin': return redirect('/')
    message = ""
    if request.method == 'POST':
        name = request.form['student_name']
        uid = request.form['uid']
        cls_name = request.form['class_name']
        folder = request.form['folder_path']
        message = train_face.enroll_face(folder, name, uid, cls_name) 
    return render_template('admin.html', msg=message)

@app.route('/teacher_hub')
def teacher_hub():
    if session.get('role') != 'Teacher': return redirect('/')
    return render_template('teacher_hub.html')

@app.route('/subject_teacher', methods=['GET', 'POST'])
def subject_teacher():
    if session.get('role') != 'Teacher': return redirect('/')
    message = ""
    logs = []
    my_subject = session.get('subject_teacher_of') 
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'take_attendance':
            cls = request.form['class_name']
            per = request.form['period']
            date_val = request.form['date']
            check.run_class_session(cls, my_subject, per, date_val) 
            message = f"AI Scan Complete! Attendance saved for {cls} - {my_subject}."
            
        elif action == 'get_report':
            cls = request.form['class_name']
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT student_uid, student_name, class_name, subject_name, log_date, status FROM attendance_log WHERE class_name=? AND subject_name=? ORDER BY log_date DESC", (cls, my_subject))
            logs = cursor.fetchall()
            conn.close()
            message = f"Showing records for {cls} - {my_subject}"

    return render_template('subject_teacher.html', msg=message, logs=logs, my_subject=my_subject)

@app.route('/class_teacher', methods=['GET', 'POST'])
def class_teacher():
    if session.get('role') != 'Teacher': return redirect('/')
    logs = []
    message = ""
    my_class = session.get('class_teacher_of')

    if request.method == 'POST':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT student_uid, student_name, class_name, subject_name, log_date, status FROM attendance_log WHERE class_name=? ORDER BY log_date DESC, student_name ASC", (my_class,))
        logs = cursor.fetchall()
        conn.close()
        message = f"Showing Master Report for {my_class}"

    return render_template('class_teacher.html', msg=message, logs=logs, my_class=my_class)

@app.route('/student')
def student():
    if session.get('role') != 'Student': return redirect('/')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT class_name, subject_name, log_date, status FROM attendance_log WHERE student_uid=? ORDER BY log_date DESC", (session['uid'],))
    logs = cursor.fetchall()
    conn.close()
    return render_template('student.html', username=session['username'], logs=logs)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=False)