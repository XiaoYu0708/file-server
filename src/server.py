import os
import io
import time
import threading
import shutil
import zipfile
import socket
import random
import string
import mimetypes
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, send_file, abort

try:
    import qrcode
except ImportError:
    pass

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

BASE_DIR = Path.cwd() / 'data'
ROOMS_DIR = BASE_DIR / 'rooms'
ROOMS_DIR.mkdir(parents=True, exist_ok=True)

sessions = {}

def generate_code():
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=4))

def find_session_by_code(code):
    for s in sessions.values():
        if s['code'] == code:
            return s
    return None

def get_or_create_session(sid):
    if sid not in sessions:
        sessions[sid] = {
            'id': sid,
            'code': generate_code(),
            'paired_id': None,
            'created_at': datetime.now()
        }
    return sessions[sid]

def get_room(session):
    pid = session['paired_id']
    if not pid:
        return None
    key = ''.join(sorted([session['id'], pid]))
    return key

def get_room_dir(room_key):
    d = ROOMS_DIR / room_key
    d.mkdir(parents=True, exist_ok=True)
    return d

def safe_resolve(base, path):
    full = (base / path).resolve()
    if not str(full).startswith(str(base.resolve())):
        return None
    return full

def require_session(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        sid = request.headers.get('X-Session-ID') or request.args.get('sid')
        if not sid:
            return jsonify({'error': '缺少 Session ID'}), 401
        session = get_or_create_session(sid)
        return f(session, *args, **kwargs)
    return decorated

def require_paired(f):
    @wraps(f)
    @require_session
    def decorated(session, *args, **kwargs):
        if not session['paired_id']:
            return jsonify({'error': '尚未配對'}), 403
        room = get_room(session)
        return f(session, room, *args, **kwargs)
    return decorated


# ─── API - Session ─────────────────────────────────────────

@app.route('/api/session')
@require_session
def api_session(session):
    paired_info = None
    if session['paired_id'] and session['paired_id'] in sessions:
        paired_info = {'code': sessions[session['paired_id']]['code']}
    return jsonify({
        'session_id': session['id'],
        'code': session['code'],
        'paired': session['paired_id'] is not None,
        'paired_info': paired_info
    })


@app.route('/api/session/pair', methods=['POST'])
@require_session
def api_pair(session):
    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'error': '需要 code 參數'}), 400
    
    target = find_session_by_code(data['code'])
    if not target:
        return jsonify({'error': '配對碼不存在'}), 404
    if target['id'] == session['id']:
        return jsonify({'error': '不能與自己配對'}), 400
    if target['paired_id']:
        return jsonify({'error': '該裝置已配對'}), 409

    session['paired_id'] = target['id']
    target['paired_id'] = session['id']

    room = get_room(session)
    get_room_dir(room)

    return jsonify({
        'paired': True,
        'paired_code': target['code'],
        'room': room
    })


@app.route('/api/session/unpair', methods=['POST'])
@require_session
def api_unpair(session):
    room = get_room(session)
    pid = session['paired_id']
    if pid and pid in sessions:
        sessions[pid]['paired_id'] = None
    session['paired_id'] = None
    if room:
        room_dir = get_room_dir(room)
        if room_dir.exists():
            shutil.rmtree(str(room_dir))
    return jsonify({'paired': False})


# ─── API - 檔案列表 ───────────────────────────────────────

@app.route('/api/files')
@require_paired
def list_files(session, room):
    room_dir = get_room_dir(room)
    files = []
    for f in sorted(room_dir.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        files.append({
            'name': f.name,
            'is_dir': f.is_dir(),
            'size': f.stat().st_size if f.is_file() else 0,
            'modified': datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        })
    return jsonify(files)


# ─── API - 下載 ───────────────────────────────────────────

@app.route('/api/files/<path:filepath>', methods=['GET'])
@require_paired
def download_file(session, room, filepath):
    room_dir = get_room_dir(room)
    file_path = safe_resolve(room_dir, filepath)
    if not file_path or not file_path.exists():
        abort(404)
    if file_path.is_file():
        mimetype, _ = mimetypes.guess_type(str(file_path))
        return send_file(str(file_path), mimetype=mimetype or 'application/octet-stream',
                         as_attachment=True, download_name=file_path.name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in file_path.rglob('*'):
            if f.is_file():
                arcname = str(f.relative_to(file_path.parent))
                z.write(str(f), arcname)
    buf.seek(0)
    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name=f'{file_path.name}.zip')


# ─── API - 上傳 ───────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
@require_paired
def upload_file(session, room):
    if 'file' not in request.files:
        return jsonify({'error': '未提供檔案'}), 400
    room_dir = get_room_dir(room)
    files = request.files.getlist('file')
    uploaded = []
    for f in files:
        if f.filename == '':
            continue
        rel = f.filename.replace('\\', '/')
        file_path = (room_dir / rel).resolve()
        if not str(file_path).startswith(str(room_dir.resolve())):
            return jsonify({'error': '路徑不合法'}), 403
        file_path.parent.mkdir(parents=True, exist_ok=True)
        f.save(str(file_path))
        uploaded.append(rel)
    return jsonify({'message': f'已上傳 {len(uploaded)} 個檔案', 'files': uploaded}), 201


# ─── API - 刪除 ───────────────────────────────────────────

@app.route('/api/files/<path:filepath>', methods=['DELETE'])
@require_paired
def delete_file(session, room, filepath):
    room_dir = get_room_dir(room)
    file_path = safe_resolve(room_dir, filepath)
    if not file_path:
        return jsonify({'error': '路徑不合法'}), 403
    if not file_path.exists():
        abort(404)
    if file_path.is_file():
        file_path.unlink()
    else:
        shutil.rmtree(str(file_path))
    return jsonify({'message': f'{filepath} 已刪除'})


# ─── Web UI ───────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ─── 錯誤處理 ─────────────────────────────────────────────

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': '無效的 Session'}), 401

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': '檔案不存在'}), 404

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': '檔案過大，限制 500MB'}), 413


# ─── 終端機 Banner ──────────────────────────────────────

def print_banner():
    url = f"http://{LOCAL_IP}:{PORT}"
    print(f"""
┌─────────────────────────────────────────────────────┐
│                 File Server 已啟動                  │
│                                                     │
│  {url}               │
│                                                     │""")
    try:
        import qrcode.constants
        qr = qrcode.QRCode(border=0, box_size=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(url)
        qr.make()
        m = qr.modules
        for i in range(0, len(m), 2):
            line = ''
            for j in range(len(m[i])):
                top = m[i][j]
                bot = m[i+1][j] if i+1 < len(m) else False
                if top and bot: line += '█'
                elif top and not bot: line += '▀'
                elif not top and bot: line += '▄'
                else: line += ' '
            print(f"  │ {line} │")
    except Exception:
        pass
    print(f"""  │                                                     │
│  手機掃描上方 QR Code 開啟網頁                     │
│  按 Ctrl+C 停止伺服器                              │
└─────────────────────────────────────────────────────┘
    """)


def find_free_port(start=5000, end=5100):
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return start


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# ─── 自動清理 ─────────────────────────────────────────────

def cleanup_old_files():
    while True:
        time.sleep(3600)
        now = time.time()
        cutoff = now - 86400
        for room_dir in ROOMS_DIR.iterdir():
            if not room_dir.is_dir():
                continue
            for f in list(room_dir.iterdir()):
                try:
                    if f.stat().st_mtime < cutoff:
                        if f.is_file():
                            f.unlink()
                        else:
                            shutil.rmtree(str(f))
                except Exception:
                    pass
            try:
                if not any(room_dir.iterdir()):
                    room_dir.rmdir()
            except Exception:
                pass


# ─── 啟動 ─────────────────────────────────────────────────

if __name__ == '__main__':
    t = threading.Thread(target=cleanup_old_files, daemon=True)
    t.start()
    LOCAL_IP = get_local_ip()
    PORT = find_free_port()
    if PORT != 5000:
        print(f"⚠️  Port 5000 已被占用，自動切換至 Port {PORT}")
    print_banner()
    app.run(host='0.0.0.0', port=PORT, debug=False)
