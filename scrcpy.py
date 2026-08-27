from threading import Thread, Lock
import subprocess
import socket
import time
import sys

ADB_PATH = "adb"
SCRCPY_SERVER_PATH = "scrcpy-server"
DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
LOCAL_PORT = 5555

class Scrcpy:
    def __init__(self):
        self.video_socket = None
        self.audio_socket = None
        self.control_socket = None
        self.android_thread = None
        self.video_thread = None
        self.audio_thread = None
        self.control_thread = None
        self.android_process = None
        self.lock = Lock()

    def push_server_to_device(self):
        print("Scrcpy: Pushing scrcpy-server.jar to device...")
        result = subprocess.run([ADB_PATH, "push", SCRCPY_SERVER_PATH, DEVICE_SERVER_PATH], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Scrcpy: Error pushing server: {result.stderr}")
            return False
        return True

    def setup_adb_forward(self):
        print(f"Scrcpy: Setting up ADB forward: tcp:{LOCAL_PORT} -> localabstract:scrcpy")
        subprocess.run([ADB_PATH, "forward", f"tcp:{LOCAL_PORT}", "localabstract:scrcpy"], check=True)

    def start_server(self):
        print("Scrcpy: Starting scrcpy server in background...")
        cmd = [
            ADB_PATH, "shell",
            # log_level=info video_bit_rate=2000000 max_size=600 max_fps=15 stay_awake=true
            (f"CLASSPATH={DEVICE_SERVER_PATH} app_process / com.genymobile.scrcpy.Server 3.1 "
                "tunnel_forward=true log_level=info audio_codec=aac max_fps=15 stay_awake=true "
                "video_bit_rate=" + self.video_bit_rate)
        ]
        
        self.android_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while not self.stop:
            stderr_line = self.android_process.stderr.readline().decode().strip()
            if not stderr_line:
                break
            
            print(f"Scrcpy: Server error: {stderr_line}")
            if stderr_line.find(f"Capture/encoding error") >= 0:
                self.android_process.terminate()
                break
        self.android_process.wait()
        rc = self.android_process.returncode
        is_ctrl_c = False
        if sys.platform != "win32":
            # Unix/Linux/macOS: 被信号终止时，returncode 为负的信号编号
            # SIGINT 的信号编号是 2，所以 returncode 为 -2
            if rc == -2:
                is_ctrl_c = True
        else:
            # Windows: Ctrl+C 导致的退出码通常是以下值之一
            # -1073741510 (0xC000013A): 进程被 Ctrl+C 终止
            # 3221225786 (0xC000013A 的无符号形式): 同上
            if rc in (-1073741510, 3221225786):
                is_ctrl_c = True
        if is_ctrl_c:
            self.stop = True
        print("Scrcpy: Server stopped")

    def receive_video_data(self):
        print("Scrcpy: Receiving video data (H.264)...")
        self.video_socket.recv(1)
        while not self.stop:
            data = self.video_socket.recv(20480)
            if not data:
                break
            self.video_callback(data)
        print("Scrcpy: Video data reception stopped")
        self.stop_callback(self.stop)

    def receive_audio_data(self):
        print("Scrcpy: Receiving audio data...")
        # self.audio_socket.recv(1)
        while not self.stop:
            data = self.audio_socket.recv(4096)
            if not data:
                break
            self.audio_callback(data)
        print("Scrcpy: Audio data reception stopped")

    def handle_control_conn(self):
        print("Scrcpy: Control connection established (idle)...")
        # self.control_socket.recv(1)
        while not self.stop:
            data = self.control_socket.recv(1024)
            if not data:
                break
            print("Scrcpy: Control Mesg:", data)
        print("Scrcpy: Control connection stopped")

    def scrcpy_start(self, video_callback, audio_callback, stop_callback, video_bit_rate):
        with self.lock:
            self.video_bit_rate = video_bit_rate
            self.video_callback = video_callback
            self.audio_callback = audio_callback
            self.stop_callback = stop_callback;
            self.stop = False

            result = subprocess.run([ADB_PATH, "devices"], capture_output=True, text=True)
            if "device" not in result.stdout:
                print("Scrcpy: No device found. Please connect your Android device via USB.")
                return False
            print(result.stdout)

            if not self.push_server_to_device():
                print("Scrcpy: Failed to push server files to device.")
                return False

            self.setup_adb_forward()
            self.android_thread = Thread(target=self.start_server, daemon=True)
            self.android_thread.start()
            time.sleep(1)

            # video connection
            self.video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.video_socket.connect(('localhost', LOCAL_PORT))
            print("Scrcpy: Video connection established")

            # audio connection
            self.audio_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.audio_socket.connect(('localhost', LOCAL_PORT))
            print("Scrcpy: Audio connection established")

            # contorl connection
            self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.control_socket.connect(('localhost', LOCAL_PORT))
            print("Scrcpy: Control connection established")

            self.video_thread = Thread(target=self.receive_video_data, daemon=True)
            self.audio_thread = Thread(target=self.receive_audio_data, daemon=True)
            self.control_thread = Thread(target=self.handle_control_conn, daemon=True)
            self.video_thread.start()
            self.audio_thread.start()
            self.control_thread.start()
            print("Scrcpy: Background tasks started")
            return True

    def scrcpy_stop(self):
        with self.lock:
            print("Scrcpy: Stopping Scrcpy")
            self.stop = True
            try:
                self.video_socket.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                self.control_socket.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                self.audio_socket.shutdown(socket.SHUT_RDWR)
            except:
                pass
            self.video_thread.join()
            self.audio_thread.join()
            self.control_thread.join()
            self.audio_socket.close()
            self.control_socket.close()
            self.video_socket.close()

            self.android_process.terminate()
            self.android_thread.join()
            print("Scrcpy: Scrcpy stopped")

    def scrcpy_send_control(self, data):
        self.control_socket.send(data)