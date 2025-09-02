"""
Internal Quiz Web App (single-file Flask)

Features:
- Upload a PDF that contains multiple‑choice questions AND their answer key.
- Configure time limit and number of questions to take (random subset from PDF).
- Auto-lock and submit when time is up; grade immediately and show score.
- Simple PDF parser with expected format (see below).

🧾 Expected PDF text format (simple and robust):

Each question block should look like:

1. What is 2+2?
A. 3
B. 4
C. 5
D. 22
Answer: B

2) Next question ...
A) Option 1
B) Option 2
Answer: A

Notes:
- Question number can end with "." or ")".
- Options can start with "A.", "A)", or "A:" (any of A–F supported).
- The line that marks the correct choice must be "Answer: <LETTER>".
- Put questions sequentially; blank lines are OK.

If your files use a different structure, adjust the parser in parse_pdf_text().

Run locally:
1) Create a virtualenv and install deps:
   pip install flask PyPDF2
2) Run the app:
   python app.py
3) Open http://127.0.0.1:5000

Security & persistence:
- This demo keeps uploaded quiz data in memory (QUIZ_STORE). Restarting the server clears it.
- For internal use only. For production, switch to a DB/storage and add auth/CSRF as needed.
"""

from __future__ import annotations
import io
import os
import re
import uuid
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    flash, send_from_directory, abort
)
from PyPDF2 import PdfReader

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# In-memory store: {quiz_id: Quiz}
QUIZ_STORE: Dict[str, "Quiz"] = {}

OPTION_LETTERS = ["A", "B", "C", "D", "E", "F"]

@dataclass
class Question:
    number: int
    prompt: str
    options: Dict[str, str]  # {"A": "text", ...}
    answer: str              # "A"/"B"/...

@dataclass
class Quiz:
    id: str
    title: str
    time_limit_sec: int
    questions: List[Question] = field(default_factory=list)

# ---------- PDF Parsing ----------

def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF using PyPDF2. Returns a single string."""
    reader = PdfReader(io.BytesIO(file_bytes))
    texts = []
    for page in reader.pages:
        # extract_text() handles basic text PDFs. For scanned PDFs, use OCR externally.
        t = page.extract_text() or ""
        texts.append(t)
    return "\n".join(texts)

QUESTION_START_RE = re.compile(r"^(\d+)[\.)]\s*(.*)$")
OPTION_RE         = re.compile(r"^([A-F])[\.:\)]\s*(.*)$", re.IGNORECASE)
ANSWER_RE         = re.compile(r"^Answer\s*:\s*([A-F])\s*$", re.IGNORECASE)


def parse_pdf_text(text: str) -> List[Question]:
    """Parse questions from text following the expected format.
    Returns a list of Question objects in the order they appear.
    """
    lines = [l.strip() for l in text.splitlines()]
    i = 0
    questions: List[Question] = []
    qnum_seen = set()

    while i < len(lines):
        m_q = QUESTION_START_RE.match(lines[i])
        if not m_q:
            i += 1
            continue

        qnum = int(m_q.group(1))
        prompt_first = m_q.group(2).strip()
        i += 1

        # Accumulate additional prompt lines until we hit an option or Answer or next question
        prompt_lines = [prompt_first] if prompt_first else []
        options: Dict[str, str] = {}
        answer: Optional[str] = None

        # Gather optional extra prompt lines
        while i < len(lines):
            if OPTION_RE.match(lines[i]) or ANSWER_RE.match(lines[i]) or QUESTION_START_RE.match(lines[i]):
                break
            if lines[i]:
                prompt_lines.append(lines[i])
            i += 1

        # Gather options (A–F)
        while i < len(lines):
            m_opt = OPTION_RE.match(lines[i])
            if m_opt:
                letter = m_opt.group(1).upper()
                text_opt = m_opt.group(2).strip()
                options[letter] = text_opt
                i += 1
                # allow multi-line option bodies until we hit next option/answer/question
                while i < len(lines):
                    if OPTION_RE.match(lines[i]) or ANSWER_RE.match(lines[i]) or QUESTION_START_RE.match(lines[i]):
                        break
                    if lines[i]:
                        options[letter] += " " + lines[i]
                    i += 1
                continue
            # not an option: maybe answer or next question
            break

        # Read the Answer line (optional but required for grading)
        if i < len(lines) and ANSWER_RE.match(lines[i]):
            answer = ANSWER_RE.match(lines[i]).group(1).upper()
            i += 1

        # Validate and store
        if not options:
            # skip malformed question without options
            continue
        if answer and answer not in options:
            # If the provided answer letter doesn't exist among options, ignore answer
            answer = None

        prompt = " ".join(prompt_lines).strip()
        if not prompt:
            prompt = f"Question {qnum}"

        # Avoid duplicate numbers if PDF repeats numbering
        if qnum in qnum_seen:
            # give a synthetic increasing number
            qnum = (max(q.number for q in questions) + 1) if questions else 1
        qnum_seen.add(qnum)

        questions.append(Question(number=qnum, prompt=prompt, options=options, answer=answer or ""))

    return questions

# ---------- Routes ----------

HOME_HTML = """
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quiz nội bộ từ PDF</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }
    .card { max-width: 880px; margin: 0 auto; padding: 24px; border: 1px solid #ddd; border-radius: 16px; box-shadow: 0 2px 10px rgba(0,0,0,.06); }
    label { display:block; margin: 8px 0 4px; font-weight: 600; }
    input[type="number"], input[type="file"], input[type="text"] { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 10px; }
    button { padding: 10px 16px; border: 0; border-radius: 12px; background: #2563eb; color: white; font-weight: 600; cursor: pointer; }
    button:hover { filter: brightness(0.95); }
    .muted { color: #555; font-size: 14px; }
    .flash { background: #fff8c5; border: 1px solid #ffe58f; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>⚙️ Tạo bài trắc nghiệm từ PDF</h1>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
      {% endif %}
    {% endwith %}
    <form action="{{ url_for('upload') }}" method="post" enctype="multipart/form-data">
      <label for="title">Tên bài thi (tuỳ chọn)</label>
      <input type="text" id="title" name="title" placeholder="Ví dụ: Bài kiểm tra chương 1" />

      <label for="pdf">Chọn file PDF câu hỏi + đáp án</label>
      <input type="file" id="pdf" name="pdf" accept="application/pdf" required />
      <div class="muted">Định dạng xem phần hướng dẫn ở đầu file app.py</div>

      <label for="num">Số câu muốn làm</label>
      <input type="number" id="num" name="num" min="1" value="10" required />

      <label for="time">Thời gian làm (phút)</label>
      <input type="number" id="time" name="time" min="1" value="15" required />

      <div style="margin-top:16px">
        <button type="submit">Tạo bài thi</button>
      </div>
    </form>
    <p class="muted" style="margin-top:16px">Mẹo: Nếu PDF là ảnh quét, hãy chạy OCR trước để trích xuất text.</p>
  </div>
</body>
</html>
"""

QUIZ_HTML = """
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ quiz.title or 'Bài trắc nghiệm' }}</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }
    .wrap { max-width: 960px; margin: 0 auto; }
    .head { display:flex; align-items:center; justify-content:space-between; gap: 12px; margin-bottom: 12px; }
    .timer { padding: 8px 12px; border-radius: 999px; border:1px solid #ddd; }
    .q { border: 1px solid #e5e7eb; border-radius: 16px; padding: 16px; margin: 12px 0; box-shadow: 0 1px 6px rgba(0,0,0,.05); }
    .q h3 { margin: 0 0 10px; }
    .opt { margin: 6px 0; }
    button { padding: 10px 16px; border: 0; border-radius: 12px; background: #2563eb; color: white; font-weight: 600; cursor: pointer; }
    button:hover { filter: brightness(0.95); }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>{{ quiz.title or 'Bài trắc nghiệm' }}</h1>
      <div class="timer"><span id="time"></span></div>
    </div>

    <form id="quiz-form" action="{{ url_for('submit', quiz_id=quiz.id) }}" method="post">
      {% for q in quiz.questions %}
        <div class="q">
          <h3>Câu {{ loop.index }}: {{ q.prompt }}</h3>
          {% for letter, text in q.options.items() %}
            <div class="opt">
              <label>
                <input type="radio" name="q{{ loop.parent.index0 }}" value="{{ letter }}" />
                {{ letter }}. {{ text }}
              </label>
            </div>
          {% endfor %}
        </div>
      {% endfor %}
      <button type="submit">Nộp bài</button>
    </form>
  </div>

  <script>
    const total = {{ quiz.time_limit_sec }}; // seconds
    const form = document.getElementById('quiz-form');
    const timeEl = document.getElementById('time');
    let left = total;

    function fmt(s){
      const m = Math.floor(s/60);
      const sec = s % 60;
      return `${m.toString().padStart(2,'0')}:${sec.toString().padStart(2,'0')}`;
    }

    function tick(){
      timeEl.textContent = '⏳ ' + fmt(left);
      if (left <= 0){
        // Auto-submit when time's up
        form.submit();
        return;
      }
      left -= 1;
      setTimeout(tick, 1000);
    }

    tick();
  </script>
</body>
</html>
"""

RESULT_HTML = """
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Kết quả</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }
    .wrap { max-width: 960px; margin: 0 auto; }
    .card { border:1px solid #ddd; border-radius:16px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,.06); }
    .good { color: #16a34a; }
    .bad { color: #dc2626; }
    .muted { color:#555; }
    .q { margin-top: 10px; border-top: 1px dashed #e5e7eb; padding-top: 10px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Kết quả</h1>
      <p><strong>Điểm:</strong> {{ correct }}/{{ total }} ({{ percent }}%)</p>
      <p class="muted">Bài thi: {{ title }}</p>
    </div>

    <div class="card" style="margin-top:16px">
      <h2>Chi tiết</h2>
      {% for item in details %}
        <div class="q">
          <div><strong>Câu {{ loop.index }}:</strong> {{ item.q.prompt }}</div>
          <div>Đáp án đúng: <strong>{{ item.correct }}</strong> &nbsp;|&nbsp; Bạn chọn: <strong class="{{ 'good' if item.is_correct else 'bad' }}">{{ item.user or '—' }}</strong></div>
        </div>
      {% endfor %}
    </div>

    <p class="muted" style="margin-top:16px"><a href="{{ url_for('home') }}">Tạo bài mới</a></p>
  </div>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HOME_HTML)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("pdf")
    if not file or file.filename == "":
        flash("Vui lòng chọn file PDF.")
        return redirect(url_for("home"))

    # Read settings
    title = (request.form.get("title") or "").strip()
    try:
        num = int(request.form.get("num", 10))
        tmin = int(request.form.get("time", 15))
    except ValueError:
        flash("Giá trị số câu hoặc thời gian không hợp lệ.")
        return redirect(url_for("home"))

    # Extract + parse
    try:
        data = file.read()
        text = extract_pdf_text(data)
        all_qs = parse_pdf_text(text)
    except Exception as e:
        flash(f"Lỗi đọc PDF: {e}")
        return redirect(url_for("home"))

    if not all_qs:
        flash("Không tìm thấy câu hỏi trong PDF. Kiểm tra định dạng hoặc chạy OCR nếu là ảnh.")
        return redirect(url_for("home"))

    if num > len(all_qs):
        num = len(all_qs)
        flash(f"Số câu yêu cầu lớn hơn tổng số câu trong PDF. Hệ thống sẽ dùng {num} câu.")

    sample_qs = random.sample(all_qs, num)

    quiz_id = uuid.uuid4().hex
    QUIZ_STORE[quiz_id] = Quiz(
        id=quiz_id,
        title=title,
        time_limit_sec=max(1, tmin * 60),
        questions=sample_qs,
    )

    return redirect(url_for("quiz", quiz_id=quiz_id))


@app.route("/quiz/<quiz_id>")
def quiz(quiz_id: str):
    quiz = QUIZ_STORE.get(quiz_id)
    if not quiz:
        abort(404)
    # Normalize option order (A..F)
    for q in quiz.questions:
        q.options = {k: q.options[k] for k in sorted(q.options.keys())}
    return render_template_string(QUIZ_HTML, quiz=quiz)


@app.route("/submit/<quiz_id>", methods=["POST"])
def submit(quiz_id: str):
    quiz = QUIZ_STORE.get(quiz_id)
    if not quiz:
        abort(404)

    user_answers: List[Optional[str]] = []
    for idx, q in enumerate(quiz.questions):
        val = request.form.get(f"q{idx}")
        if val:
            val = val.strip().upper()
        user_answers.append(val)

    correct = 0
    details = []
    for ans, q in zip(user_answers, quiz.questions):
        is_ok = (ans == (q.answer or None))
        if is_ok:
            correct += 1
        details.append({
            "q": q,
            "user": ans,
            "correct": q.answer or "?",
            "is_correct": is_ok,
        })

    percent = round((correct / len(quiz.questions)) * 100, 2)

    # Optionally: remove quiz from store to prevent re-entry
    # QUIZ_STORE.pop(quiz_id, None)

    return render_template_string(
        RESULT_HTML,
        correct=correct,
        total=len(quiz.questions),
        percent=percent,
        details=details,
        title=quiz.title or "Bài trắc nghiệm",
    )


if __name__ == "__main__":
    # Bind to 0.0.0.0 for internal network access if needed
    app.run(host="0.0.0.0", port=5000, debug=True)
