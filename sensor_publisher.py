#!/usr/bin/env python3
"""
MQTT Sensor Publisher với Web Control - Thiết bị giả lập có thể điều khiển từ web
Yêu cầu: pip install paho-mqtt flask flask-socketio
"""

import paho.mqtt.client as mqtt
import json
import time
import random
from datetime import datetime
import sys
import threading
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit


class TemperatureHumiditySensor:
    def __init__(self, broker_host="localhost", broker_port=1883,
                 username=None, password=None, client_id="sensor_001"):
        """
        Khởi tạo sensor
        """
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        self.client_id = client_id

        # Khởi tạo MQTT client
        self.client = mqtt.Client(client_id=self.client_id)

        # Cấu hình xác thực nếu có
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)

        # Cấu hình callbacks
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        # Topics
        self.topic_temperature = "sensors/temperature"
        self.topic_humidity = "sensors/humidity"
        self.topic_combined = "sensors/temp_humidity"
        self.topic_control = "sensors/control"

        # Trạng thái
        self.is_connected = False
        self.is_running = False
        self.sensor_enabled = True

        # Dữ liệu hiện tại
        self.current_data = {
            "temperature": 25.0,
            "humidity": 60.0,
            "timestamp": datetime.now().isoformat(),
            "status": "offline"
        }

        # Flask app
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'sensor_secret_key'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        self.setup_flask_routes()

    def setup_flask_routes(self):
        """Cấu hình Flask routes"""

        @self.app.route('/')
        def index():
            return render_template_string(SENSOR_WEB_TEMPLATE)

        @self.socketio.on('connect')
        def handle_connect():
            emit('status_update', {
                'connected': self.is_connected,
                'running': self.is_running,
                'enabled': self.sensor_enabled,
                'data': self.current_data
            })

        @self.socketio.on('toggle_sensor')
        def handle_toggle_sensor():
            self.sensor_enabled = not self.sensor_enabled
            status = "enabled" if self.sensor_enabled else "disabled"
            print(f"🎛️  Sensor {status} từ web interface")

            # Gửi trạng thái mới
            self.socketio.emit('status_update', {
                'connected': self.is_connected,
                'running': self.is_running,
                'enabled': self.sensor_enabled,
                'data': self.current_data
            })

            self.client.publish(self.topic_control+"/sub", json.dumps({
                'connected': self.is_connected,
                'running': self.is_running,
                'enabled': self.sensor_enabled,
                'data': self.current_data
            }))

        @self.socketio.on('reconnect_mqtt')
        def handle_reconnect():
            if not self.is_connected:
                threading.Thread(target=self.connect, daemon=True).start()

    def on_connect(self, client, userdata, flags, rc):
        """Callback khi kết nối thành công"""
        if rc == 0:
            self.is_connected = True
            self.current_data["status"] = "online"
            print(
                f"✅ Kết nối thành công đến broker {self.broker_host}:{self.broker_port}")

            # Subscribe topic control
            client.subscribe(self.topic_control)
            print(f"📡 Đã subscribe topic control: {self.topic_control}")

            # Cập nhật web
            self.socketio.emit('status_update', {
                'connected': self.is_connected,
                'running': self.is_running,
                'enabled': self.sensor_enabled,
                'data': self.current_data
            })
        else:
            print(f"❌ Kết nối thất bại. Mã lỗi: {rc}")

    def on_disconnect(self, client, userdata, rc):
        """Callback khi mất kết nối"""
        self.is_connected = False
        self.current_data["status"] = "offline"
        print(f"🔌 Mất kết nối đến broker. Mã: {rc}")

        # Cập nhật web
        self.socketio.emit('status_update', {
            'connected': self.is_connected,
            'running': self.is_running,
            'enabled': self.sensor_enabled,
            'data': self.current_data
        })

    def on_message(self, client, userdata, msg):
        """Callback khi nhận được message điều khiển"""
        try:
            if msg.topic == self.topic_control:
                payload = json.loads(msg.payload.decode('utf-8'))
                command = payload.get('command', '')

                if command == 'enable':
                    self.sensor_enabled = True
                    print("🎛️  Sensor được bật từ MQTT control")
                elif command == 'disable':
                    self.sensor_enabled = False
                    print("🎛️  Sensor được tắt từ MQTT control")

                # Cập nhật web
                self.socketio.emit('status_update', {
                    'connected': self.is_connected,
                    'running': self.is_running,
                    'enabled': self.sensor_enabled,
                    'data': self.current_data
                })

        except Exception as e:
            print(f"❌ Lỗi xử lý message điều khiển: {e}")

    def generate_sensor_data(self):
        """Tạo dữ liệu sensor giả lập"""
        if not self.sensor_enabled:
            return None

        # Tạo nhiệt độ và độ ẩm với biến động tự nhiên
        temperature = round(random.uniform(20.0, 35.0), 2)
        humidity = round(random.uniform(40.0, 80.0), 2)
        timestamp = datetime.now().isoformat()

        data = {
            "temperature": temperature,
            "humidity": humidity,
            "timestamp": timestamp,
            "sensor_id": self.client_id,
            "unit_temp": "°C",
            "unit_humidity": "%",
            "status": "online" if self.is_connected else "offline"
        }

        self.current_data = data
        return data

    def publish_data(self, data):
        """Publish dữ liệu lên các topics"""
        if not self.is_connected or not data:
            return False

        try:
            # Publish nhiệt độ riêng
            temp_payload = {
                "value": data["temperature"],
                "unit": data["unit_temp"],
                "timestamp": data["timestamp"],
                "sensor_id": data["sensor_id"]
            }
            # self.client.publish(self.topic_temperature, json.dumps(temp_payload))

            # Publish độ ẩm riêng
            humidity_payload = {
                "value": data["humidity"],
                "unit": data["unit_humidity"],
                "timestamp": data["timestamp"],
                "sensor_id": data["sensor_id"]
            }
            # self.client.publish(self.topic_humidity, json.dumps(humidity_payload))
            # Publish dữ liệu kết hợp
            self.client.publish(self.topic_combined, json.dumps(data))

            print(f"📤 Gửi: T={data['temperature']}°C, H={data['humidity']}%")

            # Cập nhật web
            self.socketio.emit('data_update', data)

            return True

        except Exception as e:
            print(f"❌ Lỗi khi publish: {e}")
            return False

    def connect(self):
        """Kết nối đến MQTT broker"""
        try:
            print(
                f"🔗 Đang kết nối đến {self.broker_host}:{self.broker_port}...")
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()

            # Chờ kết nối thành công
            timeout = 10
            while not self.is_connected and timeout > 0:
                time.sleep(1)
                timeout -= 1

            return self.is_connected

        except Exception as e:
            print(f"❌ Lỗi kết nối: {e}")
            return False

    def disconnect(self):
        """Ngắt kết nối"""
        self.client.loop_stop()
        self.client.disconnect()
        print("🔌 Đã ngắt kết nối")

    def run_sensor(self, interval=3):
        """Chạy sensor loop"""
        self.is_running = True
        print("🚀 Bắt đầu sensor loop...")

        while self.is_running:
            try:
                # Tạo và gửi dữ liệu
                sensor_data = self.generate_sensor_data()
                if sensor_data:
                    self.publish_data(sensor_data)

                # Chờ trước khi gửi dữ liệu tiếp theo
                time.sleep(interval)

            except Exception as e:
                print(f"❌ Lỗi trong sensor loop: {e}")
                time.sleep(1)

    def run_web_server(self):
        """Chạy web server"""
        print("🌐 Khởi động web server tại http://localhost:5000")
        self.socketio.run(self.app, host='0.0.0.0', port=5000, debug=False)

    def start(self):
        """Khởi động sensor"""
        # Kết nối MQTT
        if not self.connect():
            print("❌ Không thể kết nối đến broker")
            return

        # Chạy sensor trong thread riêng
        sensor_thread = threading.Thread(target=self.run_sensor, daemon=True)
        sensor_thread.start()

        # Chạy web server (blocking)
        self.run_web_server()

    def stop(self):
        """Dừng sensor"""
        self.is_running = False
        self.disconnect()


# Template HTML cho sensor web interface
SENSOR_WEB_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>🌡️ Temperature & Humidity Sensor</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            color: white;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
        }
        .status-card {
            background: rgba(255, 255, 255, 0.2);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            text-align: center;
        }
        .data-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        .data-card {
            background: rgba(255, 255, 255, 0.2);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
        }
        .data-value {
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }
        .controls {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 20px;
        }
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 25px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .btn-primary {
            background: linear-gradient(45deg, #4CAF50, #45a049);
            color: white;
        }
        .btn-danger {
            background: linear-gradient(45deg, #f44336, #d32f2f);
            color: white;
        }
        .btn-secondary {
            background: linear-gradient(45deg, #2196F3, #1976D2);
            color: white;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        .status-online {
            color: #4CAF50;
        }
        .status-offline {
            color: #f44336;
        }
        .timestamp {
            font-size: 0.9em;
            opacity: 0.8;
            margin-top: 10px;
        }
        @media (max-width: 600px) {
            .data-grid {
                grid-template-columns: 1fr;
            }
            .controls {
                flex-direction: column;
                align-items: center;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌡️💧 Temperature & Humidity Sensor</h1>
        
        <div class="status-card">
            <h3>📊 Sensor Status</h3>
            <div>
                <span>MQTT Connection: </span>
                <span id="mqtt-status" class="status-offline">❌ Disconnected</span>
            </div>
            <div>
                <span>Sensor State: </span>
                <span id="sensor-state" class="status-offline" style="
    background-color: white;
    font-size: 50px;
">⏸️ Disabled</span>
            </div>
        </div>
        
        <div class="data-grid">
            <div class="data-card">
                <h3>🌡️ Temperature</h3>
                <div class="data-value" id="temperature">--°C</div>
                <div class="timestamp" id="temp-time">No data</div>
            </div>
            
            <div class="data-card">
                <h3>💧 Humidity</h3>
                <div class="data-value" id="humidity">--%</div>
                <div class="timestamp" id="humidity-time">No data</div>
            </div>
        </div>
        
        <div class="controls">
            <button id="toggle-btn" class="btn-primary" onclick="toggleSensor()">
                🎛️ Toggle Sensor
            </button>
            <button class="btn-secondary" onclick="reconnectMQTT()">
                🔄 Reconnect MQTT
            </button>
        </div>
        
        <div class="status-card">
            <h3>📈 Real-time Data</h3>
            <div id="last-update">Waiting for data...</div>
        </div>
    </div>

    <script>
        const socket = io();
        
        socket.on('connect', function() {
            console.log('Connected to server');
        });
        
        socket.on('status_update', function(data) {
            updateStatus(data);
        });
        
        socket.on('data_update', function(data) {
            updateData(data);
        });
        
        function updateStatus(data) {
            // Update MQTT status
            const mqttStatus = document.getElementById('mqtt-status');
            if (data.connected) {
                mqttStatus.innerHTML = '✅ Connected';
                mqttStatus.className = 'status-online';
            } else {
                mqttStatus.innerHTML = '❌ Disconnected';
                mqttStatus.className = 'status-offline';
            }
            
            // Update sensor state
            const sensorState = document.getElementById('sensor-state');
            if (data.enabled) {
                sensorState.innerHTML = '▶️ Enabled';
                sensorState.className = 'status-online';
            } else {
                sensorState.innerHTML = '⏸️ Disabled';
                sensorState.className = 'status-offline';
            }
            
            // Update data if available
            if (data.data) {
                updateData(data.data);
            }
        }
        
        function updateData(data) {
            document.getElementById('temperature').textContent = data.temperature + '°C';
            document.getElementById('humidity').textContent = data.humidity + '%';
            
            const timestamp = new Date(data.timestamp).toLocaleString();
            document.getElementById('temp-time').textContent = timestamp;
            document.getElementById('humidity-time').textContent = timestamp;
            
            document.getElementById('last-update').textContent = 
                `Last update: ${timestamp} | T: ${data.temperature}°C, H: ${data.humidity}%`;
        }
        
        function toggleSensor() {
            socket.emit('toggle_sensor');
        }
        
        function reconnectMQTT() {
            socket.emit('reconnect_mqtt');
        }
        
        // Auto-refresh every 30 seconds
        setInterval(() => {
            socket.emit('get_status');
        }, 30000);
    </script>
</body>
</html>
"""


def main():
    """Hàm main"""
    print("🌡️💧 MQTT Temperature & Humidity Sensor với Web Interface")
    print("=" * 60)

    # Cấu hình kết nối
    BROKER_HOST = "localhost"
    BROKER_PORT = 1883
    USERNAME = "nhandev"
    PASSWORD = "123456aA@"
    CLIENT_ID = "temp_humidity_sensor_001"

    # Tạo sensor
    sensor = TemperatureHumiditySensor(
        broker_host=BROKER_HOST,
        broker_port=BROKER_PORT,
        username=USERNAME,
        password=PASSWORD,
        client_id=CLIENT_ID
    )

    try:
        sensor.start()
    except KeyboardInterrupt:
        print("\n⏹️  Dừng sensor...")
        sensor.stop()
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        sensor.stop()


if __name__ == "__main__":
    main()
