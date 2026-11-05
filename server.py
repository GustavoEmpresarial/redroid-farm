#!/usr/bin/env python3
"""Redroid Farm — Servidor de Gestão e Visualização de Containers Android 13."""

from __future__ import annotations

import glob
import io
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
APKS_DIR = ROOT / "apks"
HOST = os.environ.get("REDROID_HOST", "0.0.0.0")
PORT = int(os.environ.get("REDROID_PORT", "8768"))
DOCKER_IMAGE = os.environ.get("REDROID_IMAGE", "redroid/redroid:13.0.0-latest")

DATA_DIR.mkdir(parents=True, exist_ok=True)
APKS_DIR.mkdir(parents=True, exist_ok=True)

# Cache de capturas para limitar sobrecarga
screen_cache: dict[str, tuple[float, bytes]] = {}
screen_lock = threading.Lock()
creation_lock = threading.Lock()


def run_cmd(cmd: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def run_adb(device_serial: str, adb_args: list[str], timeout: float = 8.0) -> tuple[int, str, str]:
    cmd = ["adb", "-s", device_serial] + adb_args
    return run_cmd(cmd, timeout=timeout)


def ensure_device_connected(port: int) -> bool:
    target = f"127.0.0.1:{port}"
    code, out, _ = run_cmd(["adb", "devices"], timeout=2)
    if f"{target}\tdevice" in out:
        return True
    if f"{target}\toffline" in out:
        run_cmd(["adb", "disconnect", target], timeout=2)
    run_cmd(["adb", "connect", target], timeout=3)
    code, out, _ = run_cmd(["adb", "devices"], timeout=2)
    return f"{target}\tdevice" in out


def get_docker_containers() -> list[dict]:
    cmd = ["docker", "ps", "-a", "--filter", "name=redroid", "--format", "{{json .}}"]
    code, out, err = run_cmd(cmd, timeout=8)
    if code != 0:
        return []

    containers = []
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for ln in lines:
        try:
            c = json.loads(ln)
            name = c.get("Names") or ""
            ports_str = c.get("Ports") or ""
            # Procura porta mapeada para 5555/tcp
            m = re.search(r":(\d+)->5555", ports_str)
            adb_port = int(m.group(1)) if m else None

            containers.append({
                "id": c.get("ID"),
                "name": name,
                "status": c.get("Status"),
                "state": c.get("State"),
                "running": c.get("State") == "running",
                "adb_port": adb_port,
                "adb_serial": f"127.0.0.1:{adb_port}" if adb_port else None,
                "created": c.get("CreatedAt"),
            })
        except Exception:
            continue
    missing_ports = [c for c in containers if c["adb_port"] is None]
    if missing_ports:
        code, details, _ = run_cmd(["docker", "inspect", *[c["id"] for c in missing_ports]], timeout=8)
        if code == 0:
            try:
                bindings = {
                    item["Id"]: item.get("HostConfig", {}).get("PortBindings", {}).get("5555/tcp") or []
                    for item in json.loads(details)
                }
                for container in missing_ports:
                    saved = next((ports for identifier, ports in bindings.items() if identifier.startswith(container["id"])), [])
                    if saved and saved[0].get("HostPort"):
                        port = int(saved[0]["HostPort"])
                        container["adb_port"] = port
                        container["adb_serial"] = f"127.0.0.1:{port}"
            except (ValueError, KeyError, TypeError):
                pass
    return sorted(containers, key=lambda x: x["name"])


def get_docker_stats() -> dict[str, dict]:
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
    code, out, _ = run_cmd(cmd, timeout=8)
    if code != 0:
        return {}
    stats = {}
    for ln in out.splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
            name = d.get("Name")
            if name:
                stats[name] = {
                    "cpu_pct": d.get("CPUPerc", "—"),
                    "mem_usage": d.get("MemUsage", "—"),
                    "mem_pct": d.get("MemPerc", "—"),
                    "net_io": d.get("NetIO", "—"),
                }
        except Exception:
            pass
    return stats


def get_next_available_port(start: int = 5556, containers: list[dict] | None = None) -> int:
    if containers is None:
        containers = get_docker_containers()
    used_ports = {c["adb_port"] for c in containers if c.get("adb_port")}
    port = start
    while port in used_ports:
        port += 1
    return port


def get_next_device_name(containers: list[dict]) -> str:
    names = {c["name"] for c in containers}
    number = 1
    while f"redroid-phone-{number}" in names:
        number += 1
    return f"redroid-phone-{number}"


def connect_in_background(port: int):
    def connect():
        for _ in range(20):
            if ensure_device_connected(port):
                return
            time.sleep(1)
    threading.Thread(target=connect, daemon=True).start()


def get_device_info(adb_serial: str) -> dict:
    info = {"model": "redroid", "android": "13", "battery": 100, "charging": True, "top_app": "—"}
    try:
        # Props
        code, out, _ = run_adb(adb_serial, ["shell", "getprop ro.build.version.release"], timeout=2)
        if code == 0 and out:
            info["android"] = out
        code, out, _ = run_adb(adb_serial, ["shell", "getprop ro.product.model"], timeout=2)
        if code == 0 and out:
            info["model"] = out
        # App em foco
        code, out, _ = run_adb(adb_serial, ["shell", "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -1"], timeout=2)
        if code == 0 and out:
            m = re.search(r"u0\s+([a-zA-Z0-9_\.]+(?:/[a-zA-Z0-9_\.]+)*)", out)
            if m:
                info["top_app"] = m.group(1).split("/")[-1]
            else:
                m2 = re.search(r"([a-zA-Z0-9_\.]+/[a-zA-Z0-9_\.]+)", out)
                if m2:
                    info["top_app"] = m2.group(1).split("/")[-1]
        # Proxy atual
        code, out, _ = run_adb(adb_serial, ["shell", "settings get global http_proxy"], timeout=2)
        if code == 0 and out and out not in ("null", ":0"):
            info["proxy"] = out
        else:
            info["proxy"] = None
    except Exception:
        pass
    return info


def capture_screenshot(adb_serial: str) -> bytes | None:
    now = time.time()
    with screen_lock:
        if adb_serial in screen_cache:
            ts, b = screen_cache[adb_serial]
            # Cache de 150ms para permitir streaming fluido
            if now - ts < 0.15:
                return b

    try:
        # ponytail: exec-out screencap produces raw PNG on standard out; fast loopback transfer
        p = subprocess.run(
            ["adb", "-s", adb_serial, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=2.5,
        )
        if p.returncode == 0 and len(p.stdout) > 1000:
            with screen_lock:
                screen_cache[adb_serial] = (now, p.stdout)
            return p.stdout
    except Exception:
        pass
    return None


def capture_screenshot_jpeg(adb_serial: str, quality: int = 70) -> bytes | None:
    raw_png = capture_screenshot(adb_serial)
    if not raw_png:
        return None
    try:
        im = Image.open(io.BytesIO(raw_png))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception:
        return None


def send_android_text(serial: str, text: str):
    if not text:
        return
    lines = text.split("\n")
    for li, line in enumerate(lines):
        if li > 0:
            run_adb(serial, ["shell", "input keyevent 66"])
        if not line:
            continue
        converted = ""
        for ch in line:
            if ch == " ":
                converted += "%s"
            elif ch in "\\\"'&;<>()$`|*?[]#~=!":
                converted += "\\" + ch
            else:
                converted += ch
        if converted:
            run_adb(serial, ["shell", f"input text {converted}"])


class FarmHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400):
        self._json({"ok": False, "error": message}, status=status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path

        if path in ("/", "/index.html"):
            index_file = ROOT / "index.html"
            if not index_file.is_file():
                return self.send_error(404, "index.html not found")
            data = index_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/devices/defaults":
            containers = get_docker_containers()
            return self._json({
                "ok": True,
                "name": get_next_device_name(containers),
                "port": get_next_available_port(containers=containers),
            })

        if path == "/api/status" or path == "/api/devices":
            containers = get_docker_containers()
            stats = get_docker_stats()
            results = []

            for c in containers:
                name = c["name"]
                st = stats.get(name, {})
                c["stats"] = st
                if c["running"] and c["adb_port"]:
                    conn = ensure_device_connected(c["adb_port"])
                    c["adb_online"] = conn
                    if conn:
                        c["info"] = get_device_info(c["adb_serial"])
                    else:
                        c["info"] = {}
                else:
                    c["adb_online"] = False
                    c["info"] = {}
                results.append(c)

            payload = {
                "ok": True,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "devices": results,
                "total": len(results),
                "running": sum(1 for c in results if c["running"]),
                "next_port": get_next_available_port(containers=containers),
            }
            return self._json(payload)

        # Captura de tela ao vivo do container (PNG)
        m = re.match(r"^/api/device/([^/]+)/screen\.png$", path)
        if m:
            name = m.group(1)
            containers = {c["name"]: c for c in get_docker_containers()}
            c = containers.get(name)
            if not c or not c.get("adb_serial"):
                return self.send_error(404, "Device offline")

            png_bytes = capture_screenshot(c["adb_serial"])
            if not png_bytes:
                png_bytes = (
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00"
                    b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
                )

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(png_bytes)))
            self.end_headers()
            self.wfile.write(png_bytes)
            return

        # Captura de tela leve (JPEG - rápida para streaming)
        m = re.match(r"^/api/device/([^/]+)/screen\.jpg$", path)
        if m:
            name = m.group(1)
            containers = {c["name"]: c for c in get_docker_containers()}
            c = containers.get(name)
            if not c or not c.get("adb_serial"):
                return self.send_error(404, "Device offline")

            jpg_bytes = capture_screenshot_jpeg(c["adb_serial"], quality=75)
            if not jpg_bytes:
                return self.send_error(500, "Failed to capture screen frame")

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(jpg_bytes)))
            self.end_headers()
            self.wfile.write(jpg_bytes)
            return

        # Live Stream contínuo (MJPEG)
        m = re.match(r"^/api/device/([^/]+)/stream\.mjpg$", path)
        if m:
            name = m.group(1)
            containers = {c["name"]: c for c in get_docker_containers()}
            c = containers.get(name)
            if not c or not c.get("adb_serial"):
                return self.send_error(404, "Device offline")

            ser = c["adb_serial"]
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "close")
            self.end_headers()

            try:
                while True:
                    frame = capture_screenshot_jpeg(ser, quality=70)
                    if frame:
                        header = (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                        )
                        self.wfile.write(header + frame + b"\r\n")
                    time.sleep(0.1)  # ~10 FPS fluido
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if path == "/api/apks":
            apks = [p.name for p in APKS_DIR.glob("*.apk")]
            return self._json({"ok": True, "apks": apks})

        self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}

        # Criar novo celular Redroid
        if path == "/api/devices/create":
            # Serialize validation and creation so two submissions cannot reserve the same name/port.
            with creation_lock:
                containers = get_docker_containers()
                name = body.get("name") or get_next_device_name(containers)
                if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
                    return self._error("Use letters, numbers, underscores or hyphens for the device name.")
                if any(c["name"] == name for c in containers):
                    return self._error(f"A device named {name} already exists. Choose another name.", 409)
                try:
                    port = int(body.get("port") or get_next_available_port(containers=containers))
                    width = int(body.get("width") or 720)
                    height = int(body.get("height") or 1280)
                    dpi = int(body.get("dpi") or 320)
                except (TypeError, ValueError):
                    return self._error("Port, resolution and density must be whole numbers.")
                if not 1024 <= port <= 65535:
                    return self._error("ADB port must be between 1024 and 65535.")
                if any(c.get("adb_port") == port for c in containers):
                    return self._error(f"ADB port {port} is reserved by another device, including powered-off devices.", 409)
                if not (180 <= width <= 4320 and 320 <= height <= 7680 and 72 <= dpi <= 960):
                    return self._error("Resolution or density is outside the supported range.")
                if not Path("/dev/binderfs/binder").exists():
                    return self._error("Android binder is unavailable. Run start-farm.sh to initialize the Android runtime.", 503)
                gpu = body.get("gpu", "guest")
                ram = body.get("ram", "")
                cpus = body.get("cpus", "")
                phone_data = DATA_DIR / name
                phone_data.mkdir(parents=True, exist_ok=True)
                cmd = [
                    "docker", "run", "-d", "--name", name, "--privileged",
                    "-v", "/dev/binderfs:/dev/binderfs",
                    "-v", f"{phone_data.resolve()}:/data", "-p", f"{port}:5555",
                ]
                if ram:
                    cmd += ["--memory", ram]
                if cpus:
                    cmd += ["--cpus", str(cpus)]
                cmd += [
                    DOCKER_IMAGE,
                    f"androidboot.redroid_gpu_mode={gpu}",
                    f"androidboot.redroid_width={width}",
                    f"androidboot.redroid_height={height}",
                    f"androidboot.redroid_dpi={dpi}",
                ]
                code, out, err = run_cmd(cmd, timeout=30)
                if code != 0:
                    return self._error(f"Failed to create device: {err or out}")
            connect_in_background(port)
            return self._json({"ok": True, "name": name, "port": port, "id": out})

        # Ação em container individual (start, stop, restart, delete)
        m = re.match(r"^/api/device/([^/]+)/action$", path)
        if m:
            name = m.group(1)
            action = body.get("action")
            if action not in ("start", "stop", "restart", "delete"):
                return self._error("Invalid action")

            containers = {c["name"]: c for c in get_docker_containers()}
            c = containers.get(name)

            if action == "delete":
                run_cmd(["docker", "stop", "-t", "2", name], timeout=10)
                code, out, err = run_cmd(["docker", "rm", "-f", name], timeout=10)
            elif action == "restart":
                if c and c.get("adb_serial"):
                    run_cmd(["adb", "disconnect", c["adb_serial"]], timeout=2)
                code, out, err = run_cmd(["docker", "restart", "-t", "2", name], timeout=15)
                # Reconexão rápida em background
                def reconnect_bg(port):
                    for _ in range(15):
                        time.sleep(1)
                        if ensure_device_connected(port):
                            break
                if c and c.get("adb_port"):
                    threading.Thread(target=reconnect_bg, args=(c["adb_port"],), daemon=True).start()
            elif action == "stop":
                if c and c.get("adb_serial"):
                    run_cmd(["adb", "disconnect", c["adb_serial"]], timeout=2)
                code, out, err = run_cmd(["docker", "stop", "-t", "2", name], timeout=10)
            else:
                code, out, err = run_cmd(["docker", "start", name], timeout=15)
                def connect_on_start(port):
                    for _ in range(15):
                        time.sleep(1)
                        if ensure_device_connected(port):
                            break
                if c and c.get("adb_port"):
                    threading.Thread(target=connect_on_start, args=(c["adb_port"],), daemon=True).start()

            if code != 0:
                return self._error(f"Failed to {action}: {err}")
            return self._json({"ok": True, "name": name, "action": action})

        # Ação global em todos os containers redroid
        if path == "/api/devices/all/action":
            action = body.get("action")
            containers = get_docker_containers()
            if action not in ("start", "stop", "restart"):
                return self._error("Invalid action")

            results = []
            for c in containers:
                cmd = ["docker", action]
                if action in ("stop", "restart"):
                    cmd += ["-t", "2"]
                code, out, err = run_cmd([*cmd, c["name"]], timeout=20)
                results.append({"name": c["name"], "ok": code == 0, "error": (err or out) if code != 0 else None})
                if code == 0 and action in ("start", "restart") and c.get("adb_port"):
                    connect_in_background(c["adb_port"])
            failed = [r for r in results if not r["ok"]]
            return self._json({
                "ok": not failed, "action": action,
                "count": sum(r["ok"] for r in results), "results": results,
                "error": "; ".join(f"{r['name']}: {r['error']}" for r in failed) if failed else None,
            }, status=502 if failed else 200)

        # Envio de toque ou tecla (Touch Input / Key Event)
        m = re.match(r"^/api/device/([^/]+)/input$", path)
        if m:
            name = m.group(1)
            containers = {c["name"]: c for c in get_docker_containers()}
            c = containers.get(name)
            if not c or not c.get("adb_serial"):
                return self._error("Device not found or ADB unavailable")

            ser = c["adb_serial"]
            act = body.get("action")
            if act == "tap":
                x = int(body.get("x", 0))
                y = int(body.get("y", 0))
                run_adb(ser, ["shell", f"input tap {x} {y}"])
            elif act == "swipe":
                x1, y1 = int(body.get("x1", 0)), int(body.get("y1", 0))
                x2, y2 = int(body.get("x2", 0)), int(body.get("y2", 0))
                dur = int(body.get("duration", 200))
                run_adb(ser, ["shell", f"input swipe {x1} {y1} {x2} {y2} {dur}"])
            elif act == "key":
                raw_code = str(body.get("keycode", 3)).strip()
                if re.match(r"^\d+(\s+--meta\s+\d+)?$", raw_code):
                    run_adb(ser, ["shell", f"input keyevent {raw_code}"])
                else:
                    run_adb(ser, ["shell", "input keyevent 3"])
                with screen_lock:
                    screen_cache.pop(ser, None)
            elif act in ("text", "paste"):
                text = str(body.get("text", ""))
                send_android_text(ser, text)
                # Refresh frame after typing so user sees the text immediately
                with screen_lock:
                    screen_cache.pop(ser, None)
            elif act == "launch":
                target_pkg = body.get("package", "")
                if target_pkg == "youtube":
                    run_adb(ser, ["shell", "am start -a android.intent.action.VIEW -d 'https://www.youtube.com' -p com.google.android.youtube"])
                elif target_pkg == "google_account":
                    run_adb(ser, ["shell", "am start -a android.settings.ADD_ACCOUNT_SETTINGS --es account_types com.google"])
                    def auto_sign_in():
                        time.sleep(1.2)
                        run_adb(ser, ["shell", "input tap 580 1130"])
                    threading.Thread(target=auto_sign_in, daemon=True).start()
                elif target_pkg == "aurora":
                    run_adb(ser, ["shell", "monkey -p com.aurora.store -c android.intent.category.LAUNCHER 1"])
                elif "/" in target_pkg:
                    run_adb(ser, ["shell", f"am start -n {target_pkg}"])
                elif target_pkg:
                    run_adb(ser, ["shell", f"monkey -p {target_pkg} -c android.intent.category.LAUNCHER 1"])
            return self._json({"ok": True})

        # Abrir scrcpy localmente para um container
        m = re.match(r"^/api/device/([^/]+)/scrcpy$", path)
        if m:
            name = m.group(1)
            containers = {c["name"]: c for c in get_docker_containers()}
            c = containers.get(name)
            if not c or not c.get("adb_serial"):
                return self._error("Device not connected")

            ser = c["adb_serial"]
            title = f"Redroid - {name}"
            # Abre scrcpy com aceleração e renderização no display do usuário
            subprocess.Popen([
                "scrcpy", "-s", ser,
                "--window-title", title,
                "-m", "1024", "-b", "4M", "--max-fps", "30", "--no-audio",
            ])
            return self._json({"ok": True, "launched": title})

        # Instalar APK em um ou todos os containers
        if path == "/api/apks/install":
            apk_name = body.get("apk_name")
            target = body.get("target", "all")
            if not apk_name:
                return self._error("apk_name is required")

            apk_path = APKS_DIR / apk_name
            if not apk_path.is_file():
                return self._error("APK file not found on the server")

            containers = get_docker_containers()
            if target != "all":
                containers = [c for c in containers if c["name"] == target]

            installed = []
            for c in containers:
                if c["running"] and c.get("adb_serial"):
                    ensure_device_connected(c["adb_port"])
                    code, out, err = run_adb(c["adb_serial"], ["install", "-g", "-r", str(apk_path)], timeout=30)
                    installed.append({"name": c["name"], "ok": code == 0, "out": out or err})

            return self._json({"ok": True, "results": installed})

        # Configurar permissões automáticas do PlayBots em um ou todos os celulares
        if path == "/api/devices/setup_playbots":
            target = body.get("target", "all")
            containers = get_docker_containers()
            if target != "all":
                containers = [c for c in containers if c["name"] == target]

            setup_script = r"""
appops set com.playzero.playbotsseofast SYSTEM_ALERT_WINDOW allow
appops set com.playzero.playbotsseofast WRITE_SETTINGS allow
appops set com.playzero.playbotsseofast REQUEST_INSTALL_PACKAGES allow
appops set com.playzero.playbotsseofast ACCESS_RESTRICTED_SETTINGS allow
appops set com.playzero.playbotsseofast AUTO_REVOKE_PERMISSIONS_IF_UNUSED ignore
dumpsys deviceidle whitelist +com.playzero.playbotsseofast
dumpsys deviceidle whitelist +com.google.android.youtube
pm grant com.playzero.playbotsseofast android.permission.POST_NOTIFICATIONS 2>/dev/null || true
pm grant com.playzero.playbotsseofast android.permission.GET_ACCOUNTS 2>/dev/null || true
pm grant com.playzero.playbotsseofast android.permission.READ_CONTACTS 2>/dev/null || true
cmd notification allow_listener com.playzero.playbotsseofast/.ProtonNotifListener 2>/dev/null || true
settings put secure enabled_accessibility_services com.playzero.playbotsseofast/.YouTubeWatchdogService:com.playzero.playbotsseofast/com.playzero.playbotsseofast.YouTubeWatchdogService
settings put secure accessibility_enabled 1
cmd media_session volume --stream 3 --set 3 2>/dev/null || true
settings put global auto_time 1 2>/dev/null || true
"""
            results = []
            for c in containers:
                if c["running"] and c.get("adb_serial"):
                    ensure_device_connected(c["adb_port"])
                    code, out, err = run_adb(c["adb_serial"], ["shell", setup_script], timeout=15)
                    results.append({"name": c["name"], "ok": code == 0})

            return self._json({"ok": True, "configured": results})

        # Configurar ou limpar Proxy HTTP/SOCKS do celular
        m = re.match(r"^/api/device/([^/]+)/proxy$", path)
        if m:
            name = m.group(1)
            containers = {c["name"]: c for c in get_docker_containers()}
            c = containers.get(name)
            if not c or not c.get("adb_serial"):
                return self._error("Device offline")

            ser = c["adb_serial"]
            proxy_val = body.get("proxy", "").strip()
            if proxy_val and proxy_val.lower() not in ("none", ":0", "clear"):
                run_adb(ser, ["shell", f"settings put global http_proxy {proxy_val}"])
            else:
                run_adb(ser, ["shell", "settings put global http_proxy :0"])
            return self._json({"ok": True, "proxy": proxy_val or "none"})

        self.send_error(404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), FarmHandler)
    print(f"Redroid Farm Dashboard running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
