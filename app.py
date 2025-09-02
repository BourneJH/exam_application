"""
Internal Quiz Web App (single-file Flask)

Chức năng:
- Upload PDF chứa câu hỏi và đáp án
- Cấu hình số câu muốn lấy random + thời gian làm bài
- Sinh giao diện quiz, đếm ngược, auto-submit khi hết giờ
- Tính điểm sau khi nộp
"""

from __future__ import annotations
import os
import re
import uuid
import random
import threading
import webbrowser
from dataclasses import dataclass, field
from typing import List, Dict

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    flash
)
from PyPDF2 import PdfReader

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# In-memory store: {quiz_id: Quiz}
QUIZ_STORE: Dict[str, "Quiz"] = {}

# ----------------------------
# Data Models
# ----------------------------
@dataclass
class Question:
    text: str
    options: List[str]
    answer: str  # correct option (e.g., "A")

@dataclass
class Quiz:
    questions: List[Question]
    answers: Dict[int, str] = field(default_factory=dict)
    time_limit: int = 0  # seconds


# ----------------------------
# Utils
# ----------------------------
def parse_pdf(file_path: str) -> List[Question]:
    """
    Đọc PDF và parse thành danh sách câu hỏi.
    Format yêu cầu (text trong PDF):
    Câu 1: Nội dung ...
    A. Lựa chọn 1
    B. Lựa chọn 2
    C. Lựa chọn 3
    D. Lựa chọn 4
    Đáp án: B
    """
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"

    questions: List[Question] = []
    blocks = re.split(r"Câu\\s*\\d+:", text)
    for block in blocks[1:]:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue

        qtext = lines[0]
        options = []
        answer = None
        for line in lines[1:]:
            if re.match(r"^[A-D]\\.", line):
                options.append(line)
            elif line.startswith("Đáp án"):
                m = re.search(r"([A-D])", line)
                if m:
                    answer = m.group(1)

        if options and answer:
            questions.append(Question(qtext, options, answer))
    return questions


# ----------------------------
# Routes
# ----------------------------
UPLOAD_FORM = """
<!doctype html>
<title>Tải đề thi</title>
<h1>Tải PDF câu hỏi</h1>
<form method=post enctype=multipart/form-data>
  <input type=file name=file><br><br>
  Thời gian (phút): <input type=number name=minutes value=5><br><br>
  Số câu muốn làm: <input type=number name=num value=5><br><br>
  <input type=submit value=Tải lên>
</form>
"""

@app.route("/", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        f = request.files["file"]
        if not f:
            flash("Chưa chọn file")
            return redirect(request.url)

        path = os.path.join("uploaded.pdf")
        f.save(path)

        questions = parse_pdf(path)
        if not questions:
            return "Không đọc được câu hỏi trong PDF"

        num = int(request.form.get("num", 5))
        minutes = int(request.form.get("minutes", 5))

        if num > len(questions):
            num = len(questions)
        selected = random.sample(questions, num)

        qid = str(uuid.uuid4())
        QUIZ_STORE[qid] = Quiz(selected, time_limit=minutes * 60)
        return redirect(url_for("take_quiz", quiz_id=qid))

    return UPLOAD_FORM


QUIZ_TEMPLATE = """
<!doctype html>
<title>Làm bài trắc nghiệm</title>
<h1>Bài trắc nghiệm</h1>
<div>Thời gian còn lại: <span id="timer"></span></div>
<form id="quizform" method="post">
  {% for i, q in enumerate(quiz.questions) %}
    <p><b>Câu {{i+1}}: {{q.text}}</b></p>
    {% for opt in q.options %}
      <input type="radio" name="q{{i}}" value="{{opt[0]}}"> {{opt}}<br>
    {% endfor %}
  {% endfor %}
  <br><input type="submit" value="Nộp bài">
</form>
<script>
let total={{quiz.time_limit}};
function update(){
  let m=Math.floor(total/60), s=total%60;
  document.getElementById("timer").innerText=m+":"+("0"+s).slice(-2);
  if(total<=0){document.getElementById("quizform").submit();}
  total--;
}
setInterval(update,1000); update();
</script>
"""

@app.route("/quiz/<quiz_id>", methods=["GET", "POST"])
def take_quiz(quiz_id):
    quiz = QUIZ_STORE.get(quiz_id)
    if not quiz:
        return "Quiz không tồn tại"
    if request.method == "POST":
        score = 0
        results = []
        for i, q in enumerate(quiz.questions):
            ans = request.form.get(f"q{i}")
            correct = q.answer
            results.append((q.text, ans, correct))
            if ans == correct:
                score += 1
        return render_template_string(RESULT_TEMPLATE, score=score, total=len(quiz.questions), results=results)
    return render_template_string(QUIZ_TEMPLATE, quiz=quiz, enumerate=enumerate)


RESULT_TEMPLATE = """
<!doctype html>
<title>Kết quả</title>
<h1>Kết quả</h1>
<p>Điểm: {{score}} / {{total}}</p>
<ul>
{% for text, ans, correct in results %}
  <li><b>{{text}}</b><br>
  Trả lời: {{ans if ans else "Không chọn"}} | Đáp án đúng: {{correct}}</li>
{% endfor %}
</ul>
<a href="/">Làm lại</a>
"""

# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    # Tự động mở trình duyệt sau khi server start
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    # Bind tới localhost, tắt debug cho chạy thực tế
    app.run(host="127.0.0.1", port=5000, debug=False)
