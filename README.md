# QuizWiz - Flask Quiz Application

A simple role-based quiz application using Flask and SQLite.

## Features
- Teacher and student registration/login
- Password hashing
- Teacher creates quizzes and MCQ questions
- Unique 6-character quiz codes
- Shareable quiz link
- Open/close quiz
- Student quiz attempts
- Automatic scoring and percentage
- Automatic performance remarks
- Teacher result tracking
- Responsive Bootstrap UI

## Run

```bash
python -m venv venv
venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

The SQLite database `quiz.db` is created automatically on first run.
