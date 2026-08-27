from flask import Flask, render_template, request, Response, send_from_directory
from flask_socketio import SocketIO, emit, send
from scrcpy import Scrcpy
import argparse
import base64
import time
import threading
import binascii
import signal

class ScrcpyApp:
    def __init__(self, args):
        # 状态变量初始化
        self.scpy_ctx = None
        self.video_hdr = b''
        self.video_buf = b''
        self.last_key_frame = b''
        self.audio_hdr = b''
        self.audio_buf = b''
        self.tmr_stop_scpy = None
        self.tmr_restart_scpy = None
        self.clients = {}
        self.state_lock = threading.Lock()
        self.conns_lock = threading.Lock()
        self.video_lock = threading.Lock()
        self.audio_lock = threading.Lock()
        self.args = args

        # Flask & SocketIO 初始化
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'secret!'
        self.socketio = SocketIO(self.app, async_mode='threading')

        # 注册路由和事件
        self._register_routes()
        self._register_socket_events()

    def _register_routes(self):
        """注册 HTTP 路由"""
        @self.app.route('/')
        def index():
            if not self.authenticate_user():
                return Response('Authentication required.', 401,
                    {'WWW-Authenticate': 'Basic realm="Scrcpy Web Control"'}
                )
            return render_template('index.html')
        
        @self.app.route('/favicon.ico')
        def favicon():
            return send_from_directory('static', 'favicon.ico')
        
        @self.app.route('/<path:page>')
        def dynamic_page(page):
            if not self.authenticate_user():
                return Response('Authentication required.', 401, 
                    {'WWW-Authenticate': 'Basic realm="Scrcpy Web Control"'})
            try:
                if not page.endswith('.html'):
                    return Response('Forbidden', 403)
                return render_template(page)
            except Exception:
                return Response('Page not found.', 404)

    def _register_socket_events(self):
        """注册 SocketIO 事件"""
        @self.socketio.on('connect')
        def handle_connect():
            if not self.authenticate_user():
                return False
            with self.state_lock:
                if self.scpy_ctx is None:
                    print("ScrcpyApp: scpy ctx is none, initializing scpy ctx...")
                    self.scpy_ctx = Scrcpy()
                    if self.scpy_ctx.scrcpy_start(self.on_video_data, 
                            self.on_audio_data, self.on_scpy_stop, 
                            self.args.video_bit_rate):
                        print("ScrcpyApp: scrcpy started successfully.")
                    else:
                        if self.tmr_restart_scpy is not None:
                            self.tmr_restart_scpy.cancel()
                        self.tmr_restart_scpy = threading.Timer(10.0, self.delayed_scrcpy_restart)
                        self.tmr_restart_scpy.start()
                        print("ScrcpyApp: scrcpy started failed.")
                    with self.conns_lock:
                        self.clients[request.sid] = 1
                        current_clients = len(self.clients)
                else:
                    with self.video_lock, self.audio_lock:
                        if len(self.video_hdr) > 0:
                            emit('video_data', self.video_hdr, to=request.sid)
                            if len(self.last_key_frame) > 0:
                                emit('video_data', self.last_key_frame, to=request.sid)
                        
                        if len(self.audio_hdr) > 0:
                            emit('audio_data', self.audio_hdr, to=request.sid)

                        with self.conns_lock:
                            self.clients[request.sid] = 1
                            current_clients = len(self.clients)
            print(f'ScrcpyApp: Client connected. Total active clients: {current_clients}')

        @self.socketio.on('disconnect')
        def handle_disconnect():
            with self.conns_lock:
                del self.clients[request.sid]
                current_clients = len(self.clients)

            print(f'ScrcpyApp: Client disconnected. Remaining active clients: {current_clients}')

            if current_clients == 0:
                print("ScrcpyApp: All clients disconnected. Starting 15s delayed stop task...")
                if self.tmr_stop_scpy is not None:
                    self.tmr_stop_scpy.cancel()
                self.tmr_stop_scpy = threading.Timer(15.0, self.check_and_stop)
                self.tmr_stop_scpy.start()

        @self.socketio.on('control_data')
        def handle_control_data(data):
            with self.state_lock:
                if self.scpy_ctx:
                    self.scpy_ctx.scrcpy_send_control(data)

    def authenticate_user(self):
        """验证 HTTP 请求头中的 Authorization 字段"""
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            return False
        try:
            base64_credentials = auth_header.split(' ')[1]
            credentials = base64.b64decode(base64_credentials).decode('utf-8')
            username, password = credentials.split(':', 1)
            return username == self.args.username and password == self.args.password
        except Exception:
            return False

    def broadcast_video_msg(self, msg):
        with self.conns_lock:
            for sid in self.clients:
                self.socketio.emit('video_data', msg, to=sid)
    
    def broadcast_audio_msg(self, msg):
        with self.conns_lock:
            for sid in self.clients:
                self.socketio.emit('audio_data', msg, to=sid)

    def stop_scpy_nolock(self):
        """内部方法：停止 scrcpy 并重置状态（调用前需持有锁或在安全上下文中）"""
        if self.scpy_ctx is not None:
            self.scpy_ctx.scrcpy_stop()
            self.scpy_ctx = None
        self.video_hdr = b''
        self.video_buf = b''
        self.last_key_frame = b''
        self.audio_hdr = b''
        self.audio_buf = b''

    def check_and_stop(self):
        """检查并停止 scrcpy"""
        with self.state_lock, self.conns_lock:
            if len(self.clients) == 0 and self.scpy_ctx is not None:
                with self.video_lock:
                    self.stop_scpy_nolock()
                print("ScrcpyApp: No clients reconnected in 15s, scrcpy stopped.")

    def on_video_data(self, data):
        """处理 scrcpy 视频数据回调"""
        with self.video_lock:
            self.video_buf += data
            if len(self.video_hdr) == 0:
                idx = 64 + 12
                if len(self.video_buf) - idx <= 12:
                    return
                sps_len = int.from_bytes(self.video_buf[idx+8:idx+12], 'big')
                idx += 12 + sps_len
                if idx + 12 > len(self.video_buf):
                    return
                pps_len = int.from_bytes(self.video_buf[idx+8:idx+12], 'big')
                idx += 12 + pps_len
                if idx > len(self.video_buf):
                    return

                self.video_hdr = self.video_buf[0:idx]
                self.video_buf = self.video_buf[idx:]
                self.broadcast_video_msg(self.video_hdr)
            
            while True:
                if len(self.video_buf) <= 12:
                    return
                l = int.from_bytes(self.video_buf[8:12], 'big')
                total = 12 + l
                if total > len(self.video_buf):
                    return

                f = self.video_buf[0:total]
                idx = f.find(b'\x00\x00\x00\x01', 12)
                if idx >= 0 and 1 > 0:
                    tp = self.video_buf[idx + 4] & 0x1F
                    if tp == 5: # key frame
                        self.last_key_frame = f
                    # elif len(self.last_key_frame) > 10*1024*1024:
                    #    pass
                    # elif len(self.last_key_frame) > 0:
                    #    self.last_key_frame += f

                self.broadcast_video_msg(f)
                self.video_buf = self.video_buf[total:]

    def on_audio_data(self, data):
        # print('audio data:', binascii.hexlify(data, ' '))
        with self.audio_lock:
            self.audio_buf += data
            if len(self.audio_hdr) == 0:
                if len(self.audio_buf) <= 16:
                    return
                fl = int.from_bytes(self.audio_buf[12:16], 'big')
                if len(self.audio_buf) < 16 + fl:
                    return
                self.audio_hdr = self.audio_buf[0:16+fl]
                self.audio_buf = self.audio_buf[16+fl:]
                self.broadcast_audio_msg(self.audio_hdr)
            
            while True:
                if len(self.audio_buf) <= 12:
                    return
                fl = int.from_bytes(self.audio_buf[8:12], 'big')
                if len(self.audio_buf) < 12 + fl:
                    return
                f = self.audio_buf[0:12+fl]
                self.audio_buf = self.audio_buf[12+fl:]
                self.broadcast_audio_msg(f)
    
    def wait_restart_server(self):
        """等待重启 scrcpy 服务"""
        with self.state_lock, self.video_lock:
            print('ScrcpyApp: stop scpy and delay restart scpy')
            self.stop_scpy_nolock()
            self.socketio.emit('scpy_stop', 'scpy_ctx stoped')
            if self.tmr_restart_scpy is not None:
                self.tmr_restart_scpy.cancel()
            self.tmr_restart_scpy = threading.Timer(10.0, self.delayed_scrcpy_restart)
            self.tmr_restart_scpy.start()
            print('ScrcpyApp: wait restart scpy server.')

    def on_scpy_stop(self, is_normal):
        print('ScrcpyApp: on scpy stop.')
        if is_normal:
            return
        print('ScrcpyApp: begin restart server task.')
        self.socketio.start_background_task(self.wait_restart_server)

    def delayed_scrcpy_restart(self):
        """延迟重启 scrcpy"""
        print('ScrcpyApp: scrcpy restart')
        with self.state_lock:
            self.scpy_ctx = Scrcpy()
            if self.scpy_ctx.scrcpy_start(self.on_video_data, 
                    self.on_audio_data, self.on_scpy_stop, 
                    self.args.video_bit_rate):
                print("ScrcpyApp: scrcpy restarted successfully.")
            else:
                self.scpy_ctx = None
                self.tmr_restart_scpy = threading.Timer(10.0, self.delayed_scrcpy_restart)
                self.tmr_restart_scpy.start()
                print("ScrcpyApp: scrcpy start failed.")

    def signal_handler(self, sig, frame):
        """处理 Ctrl+C 信号"""
        with self.state_lock:
            if self.scpy_ctx is not None:
                self.scpy_ctx.scrcpy_stop()
                self.scpy_ctx = None

    def run(self):
        """启动服务"""
        #signal.signal(signal.SIGINT, self.signal_handler)
        self.socketio.run(self.app, host=self.args.host, port=self.args.port)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Web server for scrcpy')
    parser.add_argument('--video_bit_rate', default="1024000", help='scrcpy video bit rate')
    parser.add_argument('--host', default='0.0.0.0', help='host to bind the web server to')
    parser.add_argument('--port', type=int, default=5000, help='port to bind the web server to')
    parser.add_argument('--username', default="scrcpy", help='web server login username')
    parser.add_argument('--password', default="4qw!u", help='web server login password')
    args = parser.parse_args()

    server = ScrcpyApp(args)
    server.run()