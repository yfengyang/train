"""
火车时刻表H5应用 - 单列监控 + 后台管理
黄河路站 <-> 牛行车站 往返
"""
import asyncio
import json
import os
import random
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
import threading
import hashlib

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

# ==================== 配置文件 ====================
CONFIG_FILE = 'timetable.json'
ADMIN_PASSWORD = 'admin123'  # 默认管理员密码

# ==================== 默认时刻表 ====================
DEFAULT_TIMETABLE = [
    # 去程 黄河路站 -> 牛行车站
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '06:30', 'arrival': '07:15', 'interval': 20},
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '07:00', 'arrival': '07:45', 'interval': 20},
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '07:30', 'arrival': '08:15', 'interval': 20},
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '08:00', 'arrival': '08:45', 'interval': 20},
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '08:30', 'arrival': '09:15', 'interval': 20},
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '09:00', 'arrival': '09:45', 'interval': 20},
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '09:30', 'arrival': '10:15', 'interval': 20},
    {'id': 'S001', 'direction': 'outbound', 'from': '黄河路站', 'to': '牛行车站', 'departure': '10:00', 'arrival': '10:45', 'interval': 20},
    # 返程 牛行车站 -> 黄河路站
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '06:45', 'arrival': '07:30', 'interval': 20},
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '07:15', 'arrival': '08:00', 'interval': 20},
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '07:45', 'arrival': '08:30', 'interval': 20},
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '08:15', 'arrival': '09:00', 'interval': 20},
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '08:45', 'arrival': '09:30', 'interval': 20},
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '09:15', 'arrival': '10:00', 'interval': 20},
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '09:45', 'arrival': '10:30', 'interval': 20},
    {'id': 'S002', 'direction': 'return', 'from': '牛行车站', 'to': '黄河路站', 'departure': '10:15', 'arrival': '11:00', 'interval': 20},
]

# ==================== 数据管理 ====================
def load_timetable():
    """从文件加载时刻表"""
    global current_timetable
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                current_timetable = data.get('schedules', DEFAULT_TIMETABLE)
                print(f"[DATA] Loaded {len(current_timetable)} schedules from file")
        except Exception as e:
            print(f"[DATA] Load error: {e}, using default")
            current_timetable = DEFAULT_TIMETABLE[:]
    else:
        current_timetable = DEFAULT_TIMETABLE[:]
        save_timetable()

def save_timetable():
    """保存时刻表到文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'schedules': current_timetable, 'updated': datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
        print(f"[DATA] Saved {len(current_timetable)} schedules to file")
    except Exception as e:
        print(f"[DATA] Save error: {e}")

# 当前时刻表
current_timetable = []

# 运行时状态
current_schedules = []

def init_schedules():
    """初始化所有班次状态"""
    global current_schedules
    current_schedules = []
    for i, schedule in enumerate(current_timetable):
        current_schedules.append({
            **schedule,
            'status': '候车' if i < 2 else '候车',
            'delay': 0,
            'manual_departed': False,  # 手动标记已发车
            'platform': '1',
        })

load_timetable()
init_schedules()

# ==================== 认证管理 ====================
def verify_password(pwd):
    """验证管理员密码"""
    return hashlib.md5(pwd.encode()).hexdigest() == hashlib.md5(ADMIN_PASSWORD.encode()).hexdigest()

connected_websockets = []

# ==================== 数据模拟 ====================
def simulate_updates():
    """模拟火车状态更新"""
    global current_schedules

    now = datetime.now()
    current_minutes = now.hour * 60 + now.minute

    for schedule in current_schedules:
        # 如果手动标记已发车，保持已发车状态
        if schedule.get('manual_departed', False):
            schedule['status'] = '已发车'
            continue

        dep_parts = schedule['departure'].split(':')
        dep_minutes = int(dep_parts[0]) * 60 + int(dep_parts[1])

        if current_minutes < dep_minutes - 10:
            schedule['status'] = '候车'
            schedule['delay'] = 0
        elif current_minutes < dep_minutes:
            schedule['status'] = '候车'
            schedule['delay'] = 0
        elif current_minutes < dep_minutes + 5:
            schedule['status'] = '检票中'
            schedule['delay'] = 0
        elif current_minutes < dep_minutes + 15:
            schedule['status'] = '正在进站'
            schedule['delay'] = 0
        elif current_minutes < dep_minutes + 30:
            schedule['status'] = '已发车'
            schedule['delay'] = 0
        else:
            schedule['status'] = '已到达'
            schedule['delay'] = 0

        # 随机晚点
        if schedule['status'] in ['候车', '检票中'] and random.random() < 0.02:
            if schedule['delay'] == 0:
                schedule['delay'] = random.randint(1, 10)
            schedule['status'] = '晚点'

    return {
        'type': 'update',
        'schedules': current_schedules,
        'timestamp': datetime.now().isoformat()
    }

# ==================== HTTP服务器 ====================
class TrainHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/api/trains':
            self.send_json({'success': True, 'schedules': current_schedules, 'timestamp': datetime.now().isoformat()})

        elif parsed_path.path == '/api/admin/schedules':
            self.send_json({'success': True, 'schedules': current_timetable})

        elif parsed_path.path == '/api/admin/runtime':
            # 获取运行时状态（包括手动发车状态）
            self.send_json({'success': True, 'schedules': current_schedules})

        elif parsed_path.path == '/api/status':
            self.send_json({
                'success': True,
                'serverTime': datetime.now().isoformat(),
                'connectedClients': len(connected_websockets),
                'websocketAvailable': WEBSOCKETS_AVAILABLE,
                'scheduleCount': len(current_timetable)
            })

        elif parsed_path.path == '/api/admin/verify':
            params = parse_qs(parsed_path.query)
            pwd = params.get('password', [''])[0]
            self.send_json({'success': verify_password(pwd)})

        else:
            super().do_GET()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        try:
            data = json.loads(body) if body else {}
        except:
            data = {}

        if parsed_path.path == '/api/admin/schedules':
            # 验证密码
            if not verify_password(data.get('password', '')):
                self.send_json({'success': False, 'error': '密码错误'})
                return

            # 添加新班次
            new_schedule = {
                'id': data.get('id', 'S001'),
                'direction': data.get('direction', 'outbound'),
                'from': data.get('from', '黄河路站'),
                'to': data.get('to', '牛行车站'),
                'departure': data.get('departure', '08:00'),
                'arrival': data.get('arrival', '08:45'),
                'interval': int(data.get('interval', 20)),
            }
            current_timetable.append(new_schedule)
            save_timetable()
            init_schedules()
            broadcast_to_all({'type': 'reload', 'schedules': current_schedules})
            self.send_json({'success': True, 'message': '添加成功', 'schedule': new_schedule})

        elif parsed_path.path == '/api/admin/schedules/update':
            # 验证密码
            if not verify_password(data.get('password', '')):
                self.send_json({'success': False, 'error': '密码错误'})
                return

            # 更新班次
            index = data.get('index')
            if index is not None and 0 <= index < len(current_timetable):
                for key in ['id', 'direction', 'from', 'to', 'departure', 'arrival', 'interval']:
                    if key in data:
                        current_timetable[index][key] = data[key]
                save_timetable()
                init_schedules()
                broadcast_to_all({'type': 'reload', 'schedules': current_schedules})
                self.send_json({'success': True, 'message': '更新成功'})
            else:
                self.send_json({'success': False, 'error': '索引无效'})

        elif parsed_path.path == '/api/admin/schedules/delete':
            # 验证密码
            if not verify_password(data.get('password', '')):
                self.send_json({'success': False, 'error': '密码错误'})
                return

            # 删除班次
            index = data.get('index')
            if index is not None and 0 <= index < len(current_timetable):
                deleted = current_timetable.pop(index)
                save_timetable()
                init_schedules()
                broadcast_to_all({'type': 'reload', 'schedules': current_schedules})
                self.send_json({'success': True, 'message': '删除成功', 'deleted': deleted})
            else:
                self.send_json({'success': False, 'error': '索引无效'})

        elif parsed_path.path == '/api/admin/depart':
            # 手动确认发车
            if not verify_password(data.get('password', '')):
                self.send_json({'success': False, 'error': '密码错误'})
                return

            index = data.get('index')
            departed = data.get('departed', True)

            if index is not None and 0 <= index < len(current_schedules):
                current_schedules[index]['manual_departed'] = departed
                if departed:
                    current_schedules[index]['status'] = '已发车'
                else:
                    current_schedules[index]['status'] = '候车'
                broadcast_to_all({'type': 'reload', 'schedules': current_schedules})
                self.send_json({'success': True, 'message': '已发车' if departed else '已取消发车'})
            else:
                self.send_json({'success': False, 'error': '索引无效'})

        elif parsed_path.path == '/api/admin/reset':
            # 重置所有班次状态
            if not verify_password(data.get('password', '')):
                self.send_json({'success': False, 'error': '密码错误'})
                return

            for schedule in current_schedules:
                schedule['manual_departed'] = False
                schedule['status'] = '候车'
                schedule['delay'] = 0

            broadcast_to_all({'type': 'reload', 'schedules': current_schedules})
            self.send_json({'success': True, 'message': '已重置所有班次'})

        elif parsed_path.path == '/api/admin/password':
            # 修改密码
            old_pwd = data.get('oldPassword', '')
            new_pwd = data.get('newPassword', '')
            if verify_password(old_pwd):
                global ADMIN_PASSWORD
                ADMIN_PASSWORD = new_pwd
                self.send_json({'success': True, 'message': '密码修改成功'})
            else:
                self.send_json({'success': False, 'error': '原密码错误'})

        else:
            self.send_json({'success': False, 'error': '未知API'})

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass

def broadcast_to_all(data):
    """广播消息给所有WebSocket客户端"""
    for ws in connected_websockets[:]:
        try:
            asyncio.create_task(ws.send(json.dumps(data)))
        except Exception:
            if ws in connected_websockets:
                connected_websockets.remove(ws)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

# ==================== WebSocket服务器 ====================
async def websocket_handler(websocket):
    connected_websockets.append(websocket)
    print(f"[WS+] Client connected (Total: {len(connected_websockets)})")

    try:
        await websocket.send(json.dumps({
            'type': 'init',
            'schedules': current_schedules,
            'timestamp': datetime.now().isoformat()
        }))

        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get('type') == 'refresh':
                    await websocket.send(json.dumps({
                        'type': 'update',
                        'schedules': current_schedules,
                        'timestamp': datetime.now().isoformat()
                    }))
            except json.JSONDecodeError:
                pass
    except Exception as e:
        print(f"[WS-] Client error: {e}")
    finally:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)
        print(f"[WS-] Client disconnected (Total: {len(connected_websockets)})")

async def broadcast_updates():
    while True:
        await asyncio.sleep(5)
        data = simulate_updates()
        for ws in connected_websockets[:]:
            try:
                await ws.send(json.dumps(data))
            except Exception:
                if ws in connected_websockets:
                    connected_websockets.remove(ws)

async def websocket_main(port):
    print(f"[WS] WebSocket server on ws://0.0.0.0:{port}")
    async with websockets.serve(websocket_handler, '0.0.0.0', port):
        await broadcast_updates()

def run_http_server(port, public_dir):
    server = ThreadedHTTPServer(('0.0.0.0', port), lambda *args, **kwargs: TrainHTTPHandler(*args, directory=public_dir, **kwargs))
    print(f"[HTTP] HTTP server on http://0.0.0.0:{port}")
    server.serve_forever()

async def main():
    port = int(os.environ.get('PORT', 3000))
    ws_port = port + 1
    public_dir = os.path.join(os.path.dirname(__file__), 'public')

    print("=" * 60)
    print("       Train Timetable H5 - Admin System")
    print("=" * 60)
    print(f"   Homepage:    http://localhost:{port}")
    print(f"   Admin Panel: http://localhost:{port}/admin.html")
    print("=" * 60)
    print(f"   Default Password: admin123")
    print("=" * 60)

    http_thread = threading.Thread(target=run_http_server, args=(port, public_dir), daemon=True)
    http_thread.start()

    if WEBSOCKETS_AVAILABLE:
        await websocket_main(ws_port)
    else:
        while True:
            await asyncio.sleep(3600)

if __name__ == '__main__':
    if WEBSOCKETS_AVAILABLE:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n[BYE] Server stopped")
    else:
        port = int(os.environ.get('PORT', 3000))
        public_dir = os.path.join(os.path.dirname(__file__), 'public')
        print(f"[HTTP] HTTP server on http://0.0.0.0:{port}")
        server = ThreadedHTTPServer(('0.0.0.0', port), lambda *args, **kwargs: TrainHTTPHandler(*args, directory=public_dir, **kwargs))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
