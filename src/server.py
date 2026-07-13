import os
import sys
import io
import zipfile
import socket
import random
import string
import mimetypes
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, jsonify, send_file, abort

try:
    import qrcode
except ImportError:
    pass

if getattr(sys, 'frozen', False):
    template_dir = os.path.join(sys._MEIPASS, 'templates')
    app = Flask(__name__, template_folder=template_dir)
else:
    app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

SHARED_PATH = None
PAIR_CODE = None
LOCAL_IP = None
PORT = 5000


def find_free_port(start=5000, end=5100):
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return start


def pick_shared_path():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askdirectory(title='選擇共享目錄（所有上傳的檔案將存放在此）')
        root.destroy()
        if path:
            return Path(path).resolve()
    except Exception:
        pass
    default = Path("C:\\FileShare")
    print(f"使用預設路徑: {default}")
    return default


def generate_pair_code():
    return ''.join(random.choices(string.digits, k=6))


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        code = request.headers.get('X-Pair-Code') or request.args.get('code')
        if not code or code != PAIR_CODE:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '無效的配對碼'}), 401
            abort(401)
        return f(*args, **kwargs)
    return decorated


def safe_resolve(path):
    full = (SHARED_PATH / path).resolve()
    if not str(full).startswith(str(SHARED_PATH)):
        return None
    return full


def get_file_list(dir_path=None):
    base = SHARED_PATH if dir_path is None else (SHARED_PATH / dir_path)
    if not base.exists() or not base.is_dir():
        return []

    files = []
    for f in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        rel = str(f.relative_to(SHARED_PATH))
        files.append({
            'name': rel,
            'is_dir': f.is_dir(),
            'size': f.stat().st_size if f.is_file() else 0,
            'modified': datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        })
    return files


# ─── Web UI ───────────────────────────────────────────────

@app.route('/')
def index():
    files = get_file_list()
    return render_template('index.html',
                         local_ip=LOCAL_IP,
                         port=PORT,
                         files=files)


# ─── API - 配對 ───────────────────────────────────────────

@app.route('/api/pair')
def get_pair():
    return jsonify({
        'code': PAIR_CODE,
        'ip': LOCAL_IP,
        'port': PORT
    })


# ─── API - 檔案列表 ───────────────────────────────────────

@app.route('/api/files')
@require_auth
def list_files():
    prefix = request.args.get('dir', '')
    files = get_file_list(prefix) if prefix else get_file_list()
    return jsonify(files)


# ─── API - 下載 ───────────────────────────────────────────

@app.route('/api/files/<path:filepath>', methods=['GET'])
@require_auth
def download_file(filepath):
    file_path = safe_resolve(filepath)
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
@require_auth
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '未提供檔案'}), 400
    files = request.files.getlist('file')
    uploaded = []
    for f in files:
        if f.filename == '':
            continue
        rel = f.filename.replace('\\', '/')
        file_path = (SHARED_PATH / rel).resolve()
        if not str(file_path).startswith(str(SHARED_PATH)):
            return jsonify({'error': '路徑不合法'}), 403
        file_path.parent.mkdir(parents=True, exist_ok=True)
        f.save(str(file_path))
        uploaded.append(rel)
    return jsonify({'message': f'已上傳 {len(uploaded)} 個檔案', 'files': uploaded}), 201


# ─── API - 刪除 ───────────────────────────────────────────

@app.route('/api/files/<path:filepath>', methods=['DELETE'])
@require_auth
def delete_file(filepath):
    file_path = safe_resolve(filepath)
    if not file_path:
        return jsonify({'error': '路徑不合法'}), 403
    if not file_path.exists():
        abort(404)
    if file_path.is_file():
        file_path.unlink()
    else:
        import shutil
        shutil.rmtree(str(file_path))
    return jsonify({'message': f'{filepath} 已刪除'})


# ─── 錯誤處理 ─────────────────────────────────────────────

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': '無效的配對碼'}), 401


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': '檔案不存在'}), 404


@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': '檔案過大，限制 500MB'}), 413


def print_server_banner():
    url = f"http://{LOCAL_IP}:{PORT}"
    print(f"""
┌─────────────────────────────────────────────────────┐
│               File Server 已啟動                    │
│                                                     │
│  Web 介面:  {url}         │
│  配對碼:     {PAIR_CODE}                                    │
│  共享目錄:   {SHARED_PATH}│
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
                if top and bot:     line += '█'
                elif top and not bot: line += '▀'
                elif not top and bot: line += '▄'
                else:               line += ' '
            print(f"  │ {line} │")
    except Exception:
        pass
    print(f"""  │                                                     │
│  手機掃描上方 QR Code 開啟網頁                     │
│  按 Ctrl+C 停止伺服器                              │
└─────────────────────────────────────────────────────┘
    """)


# ─── 啟動 ─────────────────────────────────────────────────

if __name__ == '__main__':
    SHARED_PATH = pick_shared_path()
    PAIR_CODE = generate_pair_code()
    LOCAL_IP = get_local_ip()
    PORT = find_free_port()
    if PORT != 5000:
        print(f"⚠️  Port 5000 已被占用，自動切換至 Port {PORT}")
    print(f"\n✅ 共享目錄: {SHARED_PATH}")
    print_server_banner()
    app.run(host='0.0.0.0', port=PORT, debug=False)
