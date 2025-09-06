"""
upload_questions.py
Admin app: upload Excel (.xls/.xlsx) to import questions and mark correct answers (col B contains 'x'),
and upload up to 3 images per question. Images are stored inside SQLite as BLOBs so the runner exe
can be fully standalone (we will embed questions.db into exam_app.exe).
Run: python upload_questions.py
Visit: http://127.0.0.1:5001/
"""
from flask import Flask, request, render_template_string, redirect, url_for, flash, send_file
import sqlite3
import pandas as pd
import re
from io import BytesIO
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "admin-secret-key-please-change"
DB_FILE = "questions.db"

# Regex
CHOICE_LINE_RE = re.compile(r'^([abcd])\.\s*(.+)', re.I)
Q_PREFIX_RE = re.compile(r'^câu\s*\d+\.*\s*', re.I)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            correct_label TEXT,
            image1_blob BLOB,
            image1_name TEXT,
            image1_mime TEXT,
            image2_blob BLOB,
            image2_name TEXT,
            image2_mime TEXT,
            image3_blob BLOB,
            image3_name TEXT,
            image3_mime TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_question_to_db(qtext, opts_dict, correct_label):
    # opts_dict: dict keys 'a'..'d' to text (strings). correct_label: 'a'..'d' or None
    a = opts_dict.get('a', '')
    b = opts_dict.get('b', '')
    c = opts_dict.get('c', '')
    d = opts_dict.get('d', '')
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('''INSERT INTO questions
                   (question, option_a, option_b, option_c, option_d, correct_label)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (qtext, a, b, c, d, correct_label))
    conn.commit()
    conn.close()

@app.route('/', methods=['GET'])
def index():
    return render_template_string('''
    <!doctype html>
    <title>Admin - Upload Questions</title>
    <h2>Admin: Upload Excel câu hỏi (.xls/.xlsx)</h2>
    <p>Định dạng Excel: Cột A chứa "Câu 1", các dòng bắt đầu bằng "a.", "b.", "c.", "d." tương ứng.
       Cột B: nếu ô nằm trên dòng đáp án đúng thì đánh "x".</p>
    <form method="post" action="{{ url_for('upload_excel') }}" enctype="multipart/form-data">
      <label>Chọn file Excel: <input type="file" name="excel" accept=".xls,.xlsx" required></label><br><br>
      <label><input type="checkbox" name="overwrite" checked> Ghi đè (xóa DB cũ trước khi import)</label><br><br>
      <button>Upload & Import</button>
    </form>
    <hr>
    <h3>Upload ảnh cho câu hỏi (max 3 ảnh / câu)</h3>
    <form method="post" action="{{ url_for('upload_images') }}" enctype="multipart/form-data">
      <label>Question ID: <input name="qid" required></label><br>
      <label>Chọn ảnh (png/jpg/jpeg/gif), tối đa 3: <input type="file" name="images" multiple accept="image/*"></label><br><br>
      <button>Upload ảnh</button>
    </form>
    <hr>
    <p><a href="{{ url_for('show_db') }}">Xem DB (preview)</a></p>
    ''') 

def parse_excel_dataframe(df):
    """
    Parse dataframe where:
    - first column contains lines "Câu N", "a. ...", "b. ...", ...
    - second column contains 'x' on the same row as the correct option
    Returns: list of dicts: {question, options: {'a':..,'b':..,'c':..,'d':..}, correct_label}
    """
    questions = []
    current_q = None
    opts = {}
    correct = None

    col_q = df.columns[0]
    col_a = df.columns[1] if df.shape[1] > 1 else None

    for _, row in df.iterrows():
        cell_q = row[col_q]
        cell_a = row[col_a] if col_a is not None else None

        if pd.isna(cell_q):
            continue
        text = str(cell_q).strip()
        mark = str(cell_a).strip().lower() if (col_a is not None and not pd.isna(cell_a)) else ''

        # New question
        if text.lower().startswith('câu'):
            # finalize previous if ready
            if current_q and len(opts) == 4:
                questions.append({'question': current_q, 'options': opts.copy(), 'correct': correct})
            # reset
            # remove 'Câu N' prefix from question text
            qtext = Q_PREFIX_RE.sub('', text).strip()
            # If this same cell already contains 'a.' etc (all in one cell), attempt to split
            if re.search(r'\ba\.', text, re.I):
                # split question part and the rest starting at 'a.'
                m = re.search(r'\ba\.', text, re.I)
                qtext = text[:m.start()].strip()
                rest = text[m.start():]
                # parse choices from rest
                found = {}
                for cm in re.finditer(r'([abcd])\.\s*(.+?)(?=(?:[abcd]\.|$))', rest, re.I | re.S):
                    lab = cm.group(1).lower()
                    val = cm.group(2).strip().replace('\n', ' ').strip()
                    found[lab] = val
                opts = found.copy()
                correct = None  # may need col B marks; if none found, correct stays None
                current_q = qtext
                # If we have 4 choices already, push immediately (but correct may be None)
                if len(opts) == 4:
                    questions.append({'question': current_q, 'options': opts.copy(), 'correct': correct})
                    current_q = None
                    opts = {}
                    correct = None
            else:
                current_q = qtext
                opts = {}
                correct = None
        elif CHOICE_LINE_RE.match(text):
            m = CHOICE_LINE_RE.match(text)
            lab = m.group(1).lower()
            val = m.group(2).strip()
            opts[lab] = val
            if mark == 'x':
                correct = lab
            # if after adding we have 4 options, finalize (some files place all 4 option rows then next question)
            if len(opts) == 4 and current_q:
                questions.append({'question': current_q, 'options': opts.copy(), 'correct': correct})
                current_q = None
                opts = {}
                correct = None
        else:
            # Additional text line continuing previous question (append)
            if current_q and len(opts) == 0:
                current_q += "\n" + text
            else:
                # ignore stray lines
                pass

    # finalize last if any
    if current_q and len(opts) == 4:
        questions.append({'question': current_q, 'options': opts.copy(), 'correct': correct})

    return questions

@app.route('/upload_excel', methods=['POST'])
def upload_excel():
    excel_file = request.files.get('excel')
    if not excel_file:
        flash("Không thấy file.")
        return redirect(url_for('index'))
    overwrite = request.form.get('overwrite') == 'on'

    # read into pandas from memory
    try:
        raw = excel_file.read()
        excel_io = BytesIO(raw)
        # choose engine by extension if possible
        fname = secure_filename(excel_file.filename)
        ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        if ext == 'xls':
            df = pd.read_excel(excel_io, engine='xlrd', header=0)
        else:
            # handle xlsx (openpyxl)
            df = pd.read_excel(excel_io, engine='openpyxl', header=0)
    except Exception as e:
        flash(f"Lỗi đọc Excel: {e}")
        return redirect(url_for('index'))

    # optionally overwrite DB (delete existing rows)
    if overwrite:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM questions")
        conn.commit()
        conn.close()

    parsed = parse_excel_dataframe(df)
    if not parsed:
        flash("Không tìm thấy câu hỏi hợp lệ trong file.")
        return redirect(url_for('index'))

    added = 0
    for p in parsed:
        qtext = p['question']
        opts = p['options']
        corr = p['correct']  # may be 'a'..'d' or None
        # ensure keys exist
        for k in ['a','b','c','d']:
            opts.setdefault(k, "")
        save_question_to_db(qtext, opts, corr)
        added += 1

    flash(f"Đã thêm {added} câu vào DB.")
    return redirect(url_for('index'))

@app.route('/upload_images', methods=['POST'])
def upload_images():
    qid = request.form.get('qid')
    if not qid or not qid.isdigit():
        flash("Question ID phải là số.")
        return redirect(url_for('index'))
    qid = int(qid)
    files = request.files.getlist('images')
    if not files:
        flash("Chưa chọn ảnh.")
        return redirect(url_for('index'))

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, image1_blob, image2_blob, image3_blob FROM questions WHERE id = ?", (qid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        flash("Question ID không tồn tại.")
        return redirect(url_for('index'))

    # find next free slots
    blobs = [row[1], row[2], row[3]]  # may be None
    free_slots = [i+1 for i, b in enumerate(blobs) if not b]
    saved = 0
    for f in files:
        if saved >= len(free_slots):
            break
        if f and f.filename:
            fn = secure_filename(f.filename)
            data = f.read()
            mimetype = f.mimetype or "application/octet-stream"
            slot = free_slots[saved]
            # prepare update column names
            blob_col = f"image{slot}_blob"
            name_col = f"image{slot}_name"
            mime_col = f"image{slot}_mime"
            sql = f"UPDATE questions SET {blob_col} = ?, {name_col} = ?, {mime_col} = ? WHERE id = ?"
            cur.execute(sql, (data, fn, mimetype, qid))
            saved += 1

    conn.commit()
    conn.close()
    flash(f"Đã lưu {saved} ảnh cho câu {qid}. (tối đa 3 ảnh / câu)")
    return redirect(url_for('index'))

@app.route('/show_db')
def show_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, question, option_a, option_b, option_c, option_d, correct_label FROM questions ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    html = ['<h2>Preview DB</h2>']
    for r in rows:
        qid, qtext, a, b, c, d, corr = r
        html.append(f"<h3>Câu {qid}: {qtext}</h3>")
        html.append("<ul>")
        html.append(f"<li>a. {a} {'✅' if corr=='a' else ''}</li>")
        html.append(f"<li>b. {b} {'✅' if corr=='b' else ''}</li>")
        html.append(f"<li>c. {c} {'✅' if corr=='c' else ''}</li>")
        html.append(f"<li>d. {d} {'✅' if corr=='d' else ''}</li>")
        html.append("</ul>")
        # images links
        img_links = []
        for i in (1,2,3):
            img_links.append(f'<a href="{url_for("admin_image", qid=qid, slot=i)}">Ảnh {i}</a>')
        html.append(" | ".join(img_links))
    html.append('<p><a href="/">Quay lại</a></p>')
    return "\n".join(html)

@app.route('/admin_image/<int:qid>/<int:slot>')
def admin_image(qid, slot):
    if slot < 1 or slot > 3:
        return "Slot invalid", 404
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    blob_col = f"image{slot}_blob"
    mime_col = f"image{slot}_mime"
    cur.execute(f"SELECT {blob_col}, {mime_col} FROM questions WHERE id = ?", (qid,))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        return "No image", 404
    blob, mime = row
    return send_file(BytesIO(blob), mimetype=mime, download_name=f"q{qid}_img{slot}")

if __name__ == "__main__":
    # start admin server
    import webbrowser
    port = 5001
    url = f"http://127.0.0.1:{port}/"
    print("Starting admin app. Open:", url)
    webbrowser.open(url)
    app.run(host='127.0.0.1', port=port, debug=False)
