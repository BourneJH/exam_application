import os
import random
import threading
import webbrowser
from flask import Flask, render_template_string, request
from PyPDF2 import PdfReader

app = Flask(__name__)

# Template HTML
HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
    <title>Web làm kiểm tra</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .question { margin-bottom: 20px; }
        .timer { font-weight: bold; color: red; }
    </style>
    <script>
        var totalSeconds = {{ duration }};
        function startTimer() {
            var timer = document.getElementById('timer');
            var interval = setInterval(function() {
                var minutes = Math.floor(totalSeconds / 60);
                var seconds = totalSeconds % 60;
                timer.textContent = minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
                totalSeconds--;
                if (totalSeconds < 0) {
                    clearInterval(interval);
                    document.getElementById("quizForm").submit();
                }
            }, 1000);
        }
        window.onload = startTimer;
    </script>
</head>
<body>
    <h1>Web làm kiểm tra</h1>
    {% if not questions %}
        <form action="{{ url_for('upload') }}" method="post" enctype="multipart/form-data">
            <label>Bài Trắc nghiệm (PDF): </label>
            <input type="file" name="pdf_file" required>
            <br><br>
            <label>File đáp án (TXT): </label>
            <input type="file" name="ans_file" required>
            <br><br>
            <label>Thời gian làm bài (giây): </label>
            <input type="number" name="duration" value="60" min="10" required>
            <br><br>
            <label>Số câu hỏi muốn lấy: </label>
            <input type="number" name="num_questions" value="5" min="1" required>
            <br><br>
            <button type="submit">Bắt đầu làm bài</button>
        </form>
    {% else %}
        <div class="timer">Thời gian còn lại: <span id="timer"></span></div>
        <form id="quizForm" method="post" action="{{ url_for('submit') }}">
            {% for q in questions %}
                <div class="question">
                    <p><b>Câu {{ loop.index }}:</b> {{ q }}</p>
                    <input type="checkbox" name="q{{ loop.index }}" value="A"> A<br>
                    <input type="checkbox" name="q{{ loop.index }}" value="B"> B<br>
                    <input type="checkbox" name="q{{ loop.index }}" value="C"> C<br>
                    <input type="checkbox" name="q{{ loop.index }}" value="D"> D<br>
                </div>
            {% endfor %}
            <button type="submit">Nộp bài</button>
        </form>
    {% endif %}
</body>
</html>
"""

questions = []
correct_answers = []
selected_indices = []
exam_duration = 60


def parse_pdf(file_path):
    """Đọc PDF và trả về danh sách câu hỏi (mỗi dòng 1 câu)."""
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines


def parse_answers(file_path):
    """Đọc file TXT đáp án, mỗi dòng 1 đáp án (A, B, C, D hoặc nhiều đáp án cách nhau bởi dấu ,)."""
    with open(file_path, "r", encoding="utf-8") as f:
        answers = [line.strip().upper().replace(" ", "") for line in f if line.strip()]
    return answers


@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_TEMPLATE, questions=None, duration=exam_duration)


@app.route("/upload", methods=["POST"])
def upload():
    global questions, correct_answers, selected_indices, exam_duration
    pdf_file = request.files["pdf_file"]
    ans_file = request.files["ans_file"]
    duration = int(request.form.get("duration", 60))
    num_questions = int(request.form.get("num_questions", 5))

    if pdf_file and ans_file:
        # Lưu file tạm
        pdf_path = "uploaded.pdf"
        ans_path = "answers.txt"
        pdf_file.save(pdf_path)
        ans_file.save(ans_path)

        all_questions = parse_pdf(pdf_path)
        all_answers = parse_answers(ans_path)

        # Chọn random câu hỏi + đáp án tương ứng
        total = min(len(all_questions), len(all_answers))
        selected_indices = random.sample(range(total), min(num_questions, total))
        questions = [all_questions[i] for i in selected_indices]
        correct_answers = [all_answers[i] for i in selected_indices]
        exam_duration = duration

    return render_template_string(HTML_TEMPLATE, questions=questions, duration=exam_duration)


@app.route("/submit", methods=["POST"])
def submit():
    submitted = request.form.to_dict(flat=False)
    score = 0
    details = []

    for i, ans in enumerate(correct_answers, start=1):
        chosen = submitted.get(f"q{i}", [])
        chosen_set = set([c.upper() for c in chosen])
        correct_set = set(ans.split(","))

        if chosen_set == correct_set:
            score += 1
            details.append(f"Câu {i}: Đúng ({','.join(chosen_set)})")
        else:
            details.append(f"Câu {i}: Sai. Bạn chọn {','.join(chosen_set) or 'Không chọn'}, đáp án đúng: {','.join(correct_set)}")

    result = f"Bạn đạt {score}/{len(correct_answers)} điểm.<br><br>" + "<br>".join(details)
    return result


def open_browser():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    threading.Timer(1.5, open_browser).start()
    app.run(debug=False)
