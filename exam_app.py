"""
exam_app.py
Runner app: reads questions.db (when packed with PyInstaller use --add-data "questions.db;."),
serves exam UI: set number of questions & time, random pick, shuffle answers per question,
one question per page, progress grid, finish and scoring (scale 10). Images served from DB.
Run: python exam_app.py
Visit: http://127.0.0.1:5000/
"""
from flask import Flask, session, render_template_string, request, redirect, url_for, send_file
import sqlite3
import random, time, sys, os
from io import BytesIO
import webbrowser

app = Flask(__name__)
app.secret_key = "exam-secret-key-please-change"

# When frozen by PyInstaller, resources are extracted to sys._MEIPASS
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.abspath(".")

DB_FILE = os.path.join(base_path, "questions.db")

# Helper DB functions
def get_all_question_ids():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id FROM questions")
    ids = [r[0] for r in cur.fetchall()]
    conn.close()
    return ids

def load_question_by_id(qid):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""SELECT id, question, option_a, option_b, option_c, option_d, correct_label,
                          image1_name, image1_blob IS NOT NULL, image1_blob IS NOT NULL,
                          image2_name, image2_blob IS NOT NULL,
                          image3_name, image3_blob IS NOT NULL
                   FROM questions WHERE id = ?""", (qid,))
    # Note: above uses IS NOT NULL but to fetch blob flags we will requery for blob separately when needed
    # Simpler: just fetch main columns
    cur.execute("SELECT id, question, option_a, option_b, option_c, option_d, correct_label FROM questions WHERE id = ?", (qid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    qid, qtext, a, b, c, d, corr = row
    return {
        'id': qid,
        'text': qtext,
        'option_a': a,
        'option_b': b,
        'option_c': c,
        'option_d': d,
        'correct_label': corr
    }

def get_image_info(qid, slot):
    """Return (blob, mimetype, name) or (None, None, None)"""
    if slot < 1 or slot > 3:
        return (None, None, None)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(f"SELECT image{slot}_blob, image{slot}_mime, image{slot}_name FROM questions WHERE id = ?", (qid,))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        return (None, None, None)
    return (row[0], row[1] or "application/octet-stream", row[2] or f"img{slot}")

@app.route('/image/<int:qid>/<int:slot>')
def image(qid, slot):
    blob, mime, name = get_image_info(qid, slot)
    if not blob:
        return "No image", 404
    return send_file(BytesIO(blob), mimetype=mime, download_name=name)

# Session keys:
# session['question_data'] = { "1": { id, text, choices: [ {'display_label','text','is_correct'} ], images_count:int, ... }, ... }
# session['answers'] = { "1": "a", ... }
# session['start_time'], session['time_limit_seconds']

@app.route('/', methods=['GET', 'POST'])
def index():
    total = len(get_all_question_ids())
    if request.method == 'POST':
        try:
            num_q = int(request.form.get('num_questions', '0'))
            time_minutes = int(request.form.get('time_limit', '0'))
        except:
            return "Nhập số hợp lệ", 400
        if num_q <= 0 or num_q > total:
            return f"Số câu phải trong khoảng 1..{total}", 400
        if time_minutes <= 0:
            return "Thời lượng phải > 0", 400

        # sample random question ids
        all_ids = get_all_question_ids()
        chosen = random.sample(all_ids, num_q)

        question_data = {}
        display_labels = ['a', 'b', 'c', 'd']
        for order_idx, qid in enumerate(chosen, start=1):
            q = load_question_by_id(qid)
            # original options with orig labels
            opts = [
                {'orig_label': 'a', 'text': q.get('option_a') or ''},
                {'orig_label': 'b', 'text': q.get('option_b') or ''},
                {'orig_label': 'c', 'text': q.get('option_c') or ''},
                {'orig_label': 'd', 'text': q.get('option_d') or ''}
            ]
            random.shuffle(opts)
            choices = []
            correct_display = None
            for i, o in enumerate(opts):
                dl = display_labels[i]
                is_corr = (o['orig_label'] == (q.get('correct_label') or '').lower())
                if is_corr:
                    correct_display = dl
                choices.append({'display_label': dl, 'text': o['text'], 'is_correct': is_corr})
            # count images available
            imgs = []
            for s in (1,2,3):
                blob, mime, name = get_image_info(qid, s)
                if blob:
                    imgs.append(s)
            question_data[str(order_idx)] = {
                'id': qid,
                'text': q.get('text') or '',
                'choices': choices,
                'correct_display': correct_display,
                'images': imgs
            }

        # store in session
        session['question_data'] = question_data
        session['answers'] = {}
        session['num_q'] = num_q
        session['time_limit_seconds'] = time_minutes * 60
        session['start_time'] = int(time.time())
        return redirect(url_for('exam', idx=1))

    return render_template_string('''
    <!doctype html>
    <title>Bài thi trắc nghiệm</title>
    <style>
      body { font-family: Arial, sans-serif; text-align:center; }
      .container { width: 60%; margin: auto; }
    </style>
    <div class="container">
      <h1>Bài thi trắc nghiệm</h1>
      <p>Số câu hiện có trong hệ thống: <strong>{{ total }}</strong></p>
      <form method="post">
        Số lượng câu muốn làm: <input name="num_questions" type="number" min="1" max="{{ total }}" required><br><br>
        Thời lượng (phút): <input name="time_limit" type="number" min="1" required><br><br>
        <button type="submit">Bắt đầu</button>
      </form>
    </div>
    ''', total=total)

def time_left_seconds():
    start = session.get('start_time')
    if not start:
        return None
    limit = session.get('time_limit_seconds', 0)
    elapsed = int(time.time()) - int(start)
    rem = limit - elapsed
    return max(0, rem)

@app.route('/exam/<int:idx>', methods=['GET', 'POST'])
def exam(idx):
    if 'question_data' not in session:
        return redirect(url_for('index'))
    qdata = session['question_data']
    num_q = session.get('num_q', 0)
    if idx < 1 or idx > num_q:
        return redirect(url_for('exam', idx=1))

    rem = time_left_seconds()
    if rem == 0:
        return redirect(url_for('finish'))

    if request.method == 'POST':
        chosen = request.form.get('choice')
        if chosen:
            answers = session.get('answers', {})
            answers[str(idx)] = chosen
            session['answers'] = answers

        if 'next' in request.form:
            return redirect(url_for('exam', idx=min(num_q, idx+1)))
        if 'prev' in request.form:
            return redirect(url_for('exam', idx=max(1, idx-1)))
        if 'goto' in request.form:
            goto = int(request.form.get('goto_idx', 1))
            return redirect(url_for('exam', idx=goto))
        if 'finish' in request.form:
            return redirect(url_for('finish'))

    q = qdata[str(idx)]
    answers = session.get('answers', {})
    progress = []
    for i in range(1, num_q+1):
        state = 'answered' if str(i) in answers else 'unanswered'
        progress.append({'i': i, 'state': state})
    return render_template_string('''
    <!doctype html>
    <title>Bài thi trắc nghiệm</title>
    <style>
      body { font-family: Arial, sans-serif; text-align:center; }
      .container { width: 70%; margin: auto; }
      .progress-grid { margin: 10px auto; display:flex; justify-content:center; gap:8px; flex-wrap:wrap; }
      .cell { width:34px; height:34px; line-height:34px; border-radius:4px; color:white; cursor:pointer; border:none; }
      .answered { background:#007bff; }
      .unanswered { background:#6c757d; }
      .choice { text-align:left; margin:10px auto; width:60%; }
      .nav { margin-top:15px; }
      .img { max-width:400px; margin:10px auto; }
      .timer { font-weight:bold; }
    </style>
    <div class="container">
      <h1>Bài thi trắc nghiệm</h1>
      <div>Thời gian còn lại: <span class="timer" id="timer">{{ rem }}</span> giây</div>
      <h3>Câu {{ idx }} / {{ num_q }}</h3>
      <p style="white-space:pre-line;">{{ q['text'] }}</p>
      {% if q['images'] %}
        {% for im in q['images'] %}
          <div class="img">
            <img src="{{ url_for('image', qid=q['id'], slot=im) }}" style="max-width:100%;">
          </div>
        {% endfor %}
      {% endif %}
      <form method="post">
        <div class="choice">
          {% for c in q['choices'] %}
            <div style="margin:6px 0;">
              <label>
                <input type="radio" name="choice" value="{{ c['display_label'] }}" {% if session.get('answers',{}).get(str(idx))==c['display_label'] %}checked{% endif %}>
                <strong>{{ c['display_label'] }}.</strong> {{ c['text'] }}
              </label>
            </div>
          {% endfor %}
        </div>
        <div class="nav">
          {% if idx > 1 %}
            <button name="prev">Quay lại</button>
          {% endif %}
          {% if idx < num_q %}
            <button name="next">Câu sau</button>
          {% endif %}
          <button name="finish">Kết thúc bài thi</button>
        </div>
        <br>
        <div class="progress-grid">
          {% for cell in progress %}
            <button type="submit" name="goto" onclick="document.getElementById('goto_idx').value={{cell.i}}; return true;" class="cell {{ cell.state }}">{{cell.i}}</button>
          {% endfor %}
        </div>
        <input type="hidden" id="goto_idx" name="goto_idx" value="1">
      </form>
    </div>
    <script>
      let rem = {{ rem }};
      const timerEl = document.getElementById('timer');
      function tick(){
        if(rem<=0){ window.location.href="{{ url_for('finish') }}"; return; }
        timerEl.innerText = rem;
        rem -= 1;
        setTimeout(tick, 1000);
      }
      tick();
    </script>
    ''', q=q, idx=idx, num_q=num_q, rem=rem)

@app.route('/finish')
def finish():
    question_data = session.get('question_data', {})
    answers = session.get('answers', {})
    results = []
    correct_count = 0
    for idx_str, q in question_data.items():
        chosen = answers.get(idx_str)
        correct = q.get('correct_display')
        correct_text = None
        for c in q['choices']:
            if c['display_label'] == correct:
                correct_text = c['text']
        is_right = (chosen == correct)
        if is_right:
            correct_count += 1
        results.append({'idx': int(idx_str), 'chosen': chosen, 'correct': correct, 'correct_text': correct_text, 'is_right': is_right})

    total = len(question_data)
    score = round((correct_count / total) * 10, 2) if total > 0 else 0
    return render_template_string('''
    <!doctype html>
    <title>Kết quả</title>
    <style>
      body { font-family: Arial, sans-serif; text-align:center; }
      table { margin:auto; border-collapse: collapse; }
      td, th { padding:8px 12px; border:1px solid #ccc; }
      .ok { background: #28a745; color:white; padding:4px 8px; border-radius:4px; }
      .bad { background: #dc3545; color:white; padding:4px 8px; border-radius:4px; }
    </style>
    <h1>Kết quả: {{ score }} / 10</h1>
    <table>
      <tr><th>Câu</th><th>Trạng thái</th><th>Đáp án đúng</th></tr>
      {% for r in results %}
        <tr>
          <td>{{ r.idx }}</td>
          <td>{% if r.is_right %}<span class="ok">Đúng</span>{% else %}<span class="bad">Sai</span>{% endif %}</td>
          <td>{{ r.correct }}. {{ r.correct_text }}</td>
        </tr>
      {% endfor %}
    </table>
    <br><a href="{{ url_for('index') }}"><button>Quay lại trang chính</button></a>
    ''', results=results, score=score)

if __name__ == "__main__":
    port = 5000
    url = f"http://127.0.0.1:{port}/"
    print("Starting exam app. Open:", url)
    webbrowser.open(url)
    app.run(host='127.0.0.1', port=port, debug=False)
