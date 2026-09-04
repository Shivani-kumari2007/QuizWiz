import os
import sqlite3
import string
import random
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, abort, session, g
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'quiz.db')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret-key-in-production'


# ---------------------------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('teacher', 'student'))
        );

        CREATE TABLE IF NOT EXISTS quiz (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            share_code TEXT UNIQUE NOT NULL,
            teacher_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (teacher_id) REFERENCES user (id)
        );

        CREATE TABLE IF NOT EXISTS question (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            FOREIGN KEY (quiz_id) REFERENCES quiz (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS attempt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            FOREIGN KEY (quiz_id) REFERENCES quiz (id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES user (id)
        );
    ''')
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# AUTH HELPERS
# ---------------------------------------------------------------------------

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute('SELECT * FROM user WHERE id = ?', (user_id,)).fetchone()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.user is None:
            flash('Please log in to continue.', 'info')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def teacher_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.user is None or g.user['role'] != 'teacher':
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def student_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.user is None or g.user['role'] != 'student':
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def format_dt(value):
    if not value:
        return ''
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone().strftime('%d %b %Y, %I:%M %p')
    except (TypeError, ValueError):
        return str(value)


app.jinja_env.filters['datetime'] = format_dt

# make g.user available in every template as current_user
@app.context_processor
def inject_user():
    return {'current_user': g.get('user')}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def generate_share_code():
    db = get_db()
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        exists = db.execute('SELECT 1 FROM quiz WHERE share_code = ?', (code,)).fetchone()
        if not exists:
            return code


def remark_for(percentage):
    if percentage >= 90:
        return "Outstanding! 🏆", "success"
    elif percentage >= 75:
        return "Great job! 👏", "success"
    elif percentage >= 60:
        return "Good effort — keep improving. 👍", "info"
    elif percentage >= 40:
        return "You passed, but there's room to grow. 📘", "warning"
    else:
        return "Needs improvement — review the topic and try again. 💪", "danger"


# ---------------------------------------------------------------------------
# GENERAL ROUTES
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if g.user:
        if g.user['role'] == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        return redirect(url_for('student_dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        username = request.form['username'].strip().lower()
        password = request.form['password']
        role = request.form['role']
        db = get_db()

        if role not in ('teacher', 'student'):
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('register'))

        if db.execute('SELECT 1 FROM user WHERE username = ?', (username,)).fetchone():
            flash('That username is already taken.', 'danger')
            return redirect(url_for('register'))

        db.execute(
            'INSERT INTO user (name, username, password_hash, role) VALUES (?, ?, ?, ?)',
            (name, username, generate_password_hash(password), role)
        )
        db.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM user WHERE username = ?', (username,)).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            flash(f"Welcome back, {user['name']}!", 'success')
            if user['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            return redirect(url_for('student_dashboard'))

        flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# TEACHER ROUTES
# ---------------------------------------------------------------------------

@app.route('/teacher/dashboard')
@login_required
@teacher_required
def teacher_dashboard():
    db = get_db()
    quizzes = db.execute(
        '''SELECT q.*,
                  (SELECT COUNT(*) FROM question WHERE quiz_id = q.id) AS question_count,
                  (SELECT COUNT(*) FROM attempt WHERE quiz_id = q.id) AS attempt_count
           FROM quiz q WHERE q.teacher_id = ? ORDER BY q.created_at DESC''',
        (g.user['id'],)
    ).fetchall()
    return render_template('teacher_dashboard.html', quizzes=quizzes)


@app.route('/teacher/quiz/new', methods=['GET', 'POST'])
@login_required
@teacher_required
def create_quiz():
    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form.get('description', '').strip()
        db = get_db()
        code = generate_share_code()
        cur = db.execute(
            'INSERT INTO quiz (title, description, share_code, teacher_id, created_at, is_active) '
            'VALUES (?, ?, ?, ?, ?, 1)',
            (title, description, code, g.user['id'], datetime.now(timezone.utc).isoformat())
        )
        db.commit()
        flash('Quiz created! Now add some questions.', 'success')
        return redirect(url_for('add_question', quiz_id=cur.lastrowid))

    return render_template('create_quiz.html')


def get_owned_quiz_or_404(quiz_id):
    db = get_db()
    quiz = db.execute('SELECT * FROM quiz WHERE id = ?', (quiz_id,)).fetchone()
    if quiz is None:
        abort(404)
    if quiz['teacher_id'] != g.user['id']:
        abort(403)
    return quiz


@app.route('/teacher/quiz/<int:quiz_id>/add-question', methods=['GET', 'POST'])
@login_required
@teacher_required
def add_question(quiz_id):
    quiz = get_owned_quiz_or_404(quiz_id)
    db = get_db()

    if request.method == 'POST':
        db.execute(
            '''INSERT INTO question
               (quiz_id, text, option_a, option_b, option_c, option_d, correct_option)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (quiz_id, request.form['text'].strip(),
             request.form['option_a'].strip(), request.form['option_b'].strip(),
             request.form['option_c'].strip(), request.form['option_d'].strip(),
             request.form['correct_option'])
        )
        db.commit()
        flash('Question added.', 'success')

        if 'add_and_finish' in request.form:
            return redirect(url_for('quiz_detail', quiz_id=quiz_id))
        return redirect(url_for('add_question', quiz_id=quiz_id))

    questions = db.execute('SELECT * FROM question WHERE quiz_id = ?', (quiz_id,)).fetchall()
    return render_template('add_question.html', quiz=quiz, questions=questions)


@app.route('/teacher/quiz/<int:quiz_id>/question/<int:q_id>/delete', methods=['POST'])
@login_required
@teacher_required
def delete_question(quiz_id, q_id):
    get_owned_quiz_or_404(quiz_id)
    db = get_db()
    db.execute('DELETE FROM question WHERE id = ? AND quiz_id = ?', (q_id, quiz_id))
    db.commit()
    flash('Question removed.', 'info')
    return redirect(url_for('quiz_detail', quiz_id=quiz_id))


@app.route('/teacher/quiz/<int:quiz_id>')
@login_required
@teacher_required
def quiz_detail(quiz_id):
    quiz = get_owned_quiz_or_404(quiz_id)
    db = get_db()
    questions = db.execute('SELECT * FROM question WHERE quiz_id = ?', (quiz_id,)).fetchall()
    attempts = db.execute(
        '''SELECT a.*, u.name AS student_name FROM attempt a
           JOIN user u ON u.id = a.student_id
           WHERE a.quiz_id = ? ORDER BY a.submitted_at DESC''',
        (quiz_id,)
    ).fetchall()
    join_url = url_for('join_quiz', code=quiz['share_code'], _external=True)
    return render_template('quiz_detail.html', quiz=quiz, questions=questions,
                            attempts=attempts, join_url=join_url)


@app.route('/teacher/quiz/<int:quiz_id>/toggle', methods=['POST'])
@login_required
@teacher_required
def toggle_quiz(quiz_id):
    quiz = get_owned_quiz_or_404(quiz_id)
    db = get_db()
    new_state = 0 if quiz['is_active'] else 1
    db.execute('UPDATE quiz SET is_active = ? WHERE id = ?', (new_state, quiz_id))
    db.commit()
    flash('Quiz is now ' + ('open' if new_state else 'closed') + ' for students.', 'info')
    return redirect(url_for('quiz_detail', quiz_id=quiz_id))


# ---------------------------------------------------------------------------
# STUDENT ROUTES
# ---------------------------------------------------------------------------

@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    db = get_db()
    attempts = db.execute(
        '''SELECT a.*, q.title AS quiz_title FROM attempt a
           JOIN quiz q ON q.id = a.quiz_id
           WHERE a.student_id = ? ORDER BY a.submitted_at DESC''',
        (g.user['id'],)
    ).fetchall()
    return render_template('student_dashboard.html', attempts=attempts)


@app.route('/join', methods=['GET', 'POST'])
@login_required
@student_required
def join_quiz_form():
    if request.method == 'POST':
        code = request.form['code'].strip().upper()
        return redirect(url_for('join_quiz', code=code))
    return render_template('join_quiz.html')


@app.route('/join/<code>')
@login_required
@student_required
def join_quiz(code):
    db = get_db()
    quiz = db.execute('SELECT * FROM quiz WHERE share_code = ?', (code.upper(),)).fetchone()
    if not quiz:
        flash('No quiz found for that code/link.', 'danger')
        return redirect(url_for('student_dashboard'))
    if not quiz['is_active']:
        flash('This quiz is currently closed by the teacher.', 'warning')
        return redirect(url_for('student_dashboard'))
    questions = db.execute('SELECT * FROM question WHERE quiz_id = ?', (quiz['id'],)).fetchall()
    if not questions:
        flash('This quiz has no questions yet.', 'warning')
        return redirect(url_for('student_dashboard'))
    return render_template('take_quiz.html', quiz=quiz, questions=questions)


@app.route('/quiz/<int:quiz_id>/submit', methods=['POST'])
@login_required
@student_required
def submit_quiz(quiz_id):
    db = get_db()
    quiz = db.execute('SELECT * FROM quiz WHERE id = ?', (quiz_id,)).fetchone()
    if not quiz:
        abort(404)
    questions = db.execute('SELECT * FROM question WHERE quiz_id = ?', (quiz_id,)).fetchall()

    score = 0
    total = len(questions)
    for question in questions:
        chosen = request.form.get(f'question_{question["id"]}')
        if chosen and chosen == question['correct_option']:
            score += 1

    cur = db.execute(
        'INSERT INTO attempt (quiz_id, student_id, score, total, submitted_at) VALUES (?, ?, ?, ?, ?)',
        (quiz_id, g.user['id'], score, total, datetime.now(timezone.utc).isoformat())
    )
    db.commit()
    return redirect(url_for('view_result', attempt_id=cur.lastrowid))


@app.route('/result/<int:attempt_id>')
@login_required
def view_result(attempt_id):
    db = get_db()
    attempt = db.execute(
        '''SELECT a.*, q.title AS quiz_title, q.teacher_id AS quiz_teacher_id
           FROM attempt a JOIN quiz q ON q.id = a.quiz_id WHERE a.id = ?''',
        (attempt_id,)
    ).fetchone()
    if attempt is None:
        abort(404)
    if g.user['role'] == 'student' and attempt['student_id'] != g.user['id']:
        abort(403)
    if g.user['role'] == 'teacher' and attempt['quiz_teacher_id'] != g.user['id']:
        abort(403)

    percentage = round((attempt['score'] / attempt['total']) * 100, 1) if attempt['total'] else 0
    remark_text, remark_level = remark_for(percentage)
    return render_template('result.html', attempt=attempt, percentage=percentage,
                            remark_text=remark_text, remark_level=remark_level)


# ---------------------------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message="You don't have access to that page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message="Page not found."), 404


if __name__ == '__main__':
    init_db()  # safe: uses CREATE TABLE IF NOT EXISTS
    app.run(debug=True)
