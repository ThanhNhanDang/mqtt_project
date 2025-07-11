#!/usr/bin/env python3
"""
MQTT Sensor Subscriber với Web Dashboard - Hiển thị dữ liệu và điều khiển thiết bị
Yêu cầu: pip install paho-mqtt flask flask-socketio
"""

import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime
import sys
import threading
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit


class SensorDataDisplay:
    def __init__(self, broker_host="localhost", broker_port=1883,
                 username=None, password=None, client_id="display_001"):
        """
        Khởi tạo thiết bị hiển thị
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
        self.topics = [
            "sensors/temperature",
            "sensors/humidity",
            "sensors/temp_humidity",
            "sensors/control/sub"  # Added control topic to receive state updates
        ]
        self.control_topic = "sensors/control"

        # Trạng thái
        self.is_connected = False

        # Lưu trữ dữ liệu
        self.sensor_data = {
            "temperature": {"value": 0, "unit": "°C", "timestamp": None},
            "humidity": {"value": 0, "unit": "%", "timestamp": None},
            "combined": None,
            "last_update": None,
            "sensor_states": {}  # New field to track sensor states
        }

        # Thống kê
        self.message_count = 0
        self.start_time = datetime.now()
        self.connected_devices = []

        # Flask app
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'display_secret_key'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        self.setup_flask_routes()

    def setup_flask_routes(self):
        """Cấu hình Flask routes"""

        @self.app.route('/')
        def index():
            return render_template_string(DISPLAY_WEB_TEMPLATE)

        @self.socketio.on('connect')
        def handle_connect(auth=None):
            print("🌐 Client kết nối web dashboard")
            serialized_data = self._serialize_sensor_data()
            emit('status_update', {
                'mqtt_connected': self.is_connected,
                'data': serialized_data,
                'stats': self.get_statistics()
            })

        @self.socketio.on('disconnect')
        def handle_disconnect():
            print("🌐 Client ngắt kết nối web dashboard")

        @self.socketio.on('control_device')
        def handle_control_device(data):
            command = data.get('command', '')
            device_id = data.get('device_id', 'all')

            if command in ['enable', 'disable']:
                self.send_control_command(command, device_id)
                # Update sensor state locally
                if device_id != 'all':
                    self.sensor_data["sensor_states"][device_id] = command == 'enable'
                elif command == 'enable':
                    for device in self.connected_devices:
                        self.sensor_data["sensor_states"][device] = True
                elif command == 'disable':
                    for device in self.connected_devices:
                        self.sensor_data["sensor_states"][device] = False
                print(f"🎛️  Gửi lệnh {command} đến thiết bị {device_id}")
                # Emit updated sensor data
                serialized_data = self._serialize_sensor_data()
                self.socketio.emit('data_update', {
                    'topic': self.control_topic,
                    'data': {'command': command, 'device_id': device_id},
                    'sensor_data': serialized_data,
                    'stats': self.get_statistics()
                })

        @self.socketio.on('get_status')
        def handle_get_status():
            serialized_data = self._serialize_sensor_data()
            emit('status_update', {
                'mqtt_connected': self.is_connected,
                'data': serialized_data,
                'stats': self.get_statistics()
            })

    def on_connect(self, client, userdata, flags, rc):
        """Callback khi kết nối thành công"""
        if rc == 0:
            self.is_connected = True
            print(
                f"✅ Kết nối thành công đến broker {self.broker_host}:{self.broker_port}")

            # Subscribe các topics
            for topic in self.topics:
                client.subscribe(topic)
                print(f"📡 Đã subscribe topic: {topic}")

            # Cập nhật web
            self.socketio.emit('mqtt_status', {'connected': True})

        else:
            print(f"❌ Kết nối thất bại. Mã lỗi: {rc}")

    def on_disconnect(self, client, userdata, rc):
        """Callback khi mất kết nối"""
        self.is_connected = False
        print(f"🔌 Mất kết nối đến broker. Mã: {rc}")

        # Cập nhật web
        self.socketio.emit('mqtt_status', {'connected': False})

    def on_message(self, client, userdata, msg):
        """Callback khi nhận được message"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)

            self.message_count += 1

            # Xử lý theo topic
            if topic == "sensors/temperature":
                self.handle_temperature_data(data)
            elif topic == "sensors/humidity":
                self.handle_humidity_data(data)
            elif topic == "sensors/temp_humidity":
                self.handle_combined_data(data)
            elif topic == "sensors/control/sub":
                self.handle_control_data(data)

            # Cập nhật thời gian
            self.sensor_data["last_update"] = datetime.now()

            # Create a copy of sensor_data with serialized datetimes
            serialized_data = self._serialize_sensor_data()

            # Gửi dữ liệu đến web
            self.socketio.emit('data_update', {
                'topic': topic,
                'data': data,
                'sensor_data': serialized_data,
                'stats': self.get_statistics()
            })

            print(f"📨 Nhận từ {topic}: {json.dumps(data, indent=2)}")

        except json.JSONDecodeError:
            print(f"❌ Không thể decode JSON từ topic {msg.topic}")
        except Exception as e:
            print(f"❌ Lỗi xử lý message: {e}")

    def handle_temperature_data(self, data):
        """Xử lý dữ liệu nhiệt độ"""
        self.sensor_data["temperature"] = {
            "value": data["value"],
            "unit": data["unit"],
            "timestamp": data["timestamp"],
            "sensor_id": data.get("sensor_id", "unknown")
        }

    def handle_humidity_data(self, data):
        """Xử lý dữ liệu độ ẩm"""
        self.sensor_data["humidity"] = {
            "value": data["value"],
            "unit": data["unit"],
            "timestamp": data["timestamp"],
            "sensor_id": data.get("sensor_id", "unknown")
        }

    def handle_combined_data(self, data):
        """Xử lý dữ liệu kết hợp"""
        self.sensor_data["combined"] = data

        # Cập nhật cả temperature và humidity từ dữ liệu kết hợp
        self.sensor_data["temperature"]["value"] = data["temperature"]
        self.sensor_data["humidity"]["value"] = data["humidity"]

        # Cập nhật danh sách thiết bị kết nối
        sensor_id = data.get("sensor_id", "unknown")
        if sensor_id not in self.connected_devices:
            self.connected_devices.append(sensor_id)
            # Initialize sensor state as enabled by default

            if sensor_id not in self.sensor_data["sensor_states"]:
                self.sensor_data["sensor_states"][sensor_id] = True

    def handle_control_data(self, data):
        """Xử lý dữ liệu điều khiển"""
        enabled = data.get('enabled', False)
        device_id = data.get("data", {}).get("sensor_id", "all")
        self.sensor_data["sensor_states"][device_id] = enabled
        self.socketio.emit('device_update', self.sensor_data["sensor_states"])
        print(
            f"🎛️ Cập nhật trạng thái sensor {device_id}: {'Enabled' if enabled else 'Disabled'}")

    def send_control_command(self, command, device_id="all"):
        """Gửi lệnh điều khiển đến thiết bị"""
        if not self.is_connected:
            print("❌ Chưa kết nối đến broker")
            return False

        control_data = {
            "command": command,
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
            "sender": self.client_id
        }

        try:
            self.client.publish(self.control_topic, json.dumps(control_data))
            print(f"📤 Gửi lệnh điều khiển: {command} đến {device_id}")
            return True
        except Exception as e:
            print(f"❌ Lỗi gửi lệnh điều khiển: {e}")
            return False

    def get_statistics(self):
        """Lấy thống kê"""
        uptime = datetime.now() - self.start_time
        return {
            "uptime": str(uptime).split('.')[0],
            "message_count": self.message_count,
            "connected_devices": len(self.connected_devices),
            "device_list": self.connected_devices,
            "avg_msg_per_sec": round(self.message_count / uptime.total_seconds(), 2) if uptime.total_seconds() > 0 else 0
        }

    def _serialize_sensor_data(self):
        """Serialize sensor_data to make it JSON serializable."""
        serialized_data = self.sensor_data.copy()
        if serialized_data["last_update"]:
            serialized_data["last_update"] = serialized_data["last_update"].isoformat(
            )
        if serialized_data["temperature"]["timestamp"]:
            serialized_data["temperature"]["timestamp"] = serialized_data["temperature"]["timestamp"].isoformat()
        if serialized_data["humidity"]["timestamp"]:
            serialized_data["humidity"]["timestamp"] = serialized_data["humidity"]["timestamp"].isoformat(
            )
        return serialized_data

    def evaluate_conditions(self, temperature, humidity):
        """Đánh giá điều kiện môi trường"""
        conditions = []
        alerts = []

        # Đánh giá nhiệt độ
        if temperature < 18:
            conditions.append("🥶 Quá lạnh")
            alerts.append("warning")
        elif temperature > 32:
            conditions.append("🥵 Quá nóng")
            alerts.append("danger")
        elif 20 <= temperature <= 26:
            conditions.append("😊 Nhiệt độ thoải mái")
            alerts.append("success")

        # Đánh giá độ ẩm
        if humidity < 40:
            conditions.append("🏜️ Quá khô")
            alerts.append("warning")
        elif humidity > 70:
            conditions.append("🌊 Quá ẩm")
            alerts.append("warning")
        elif 50 <= humidity <= 60:
            conditions.append("😊 Độ ẩm thoải mái")
            alerts.append("success")

        return {
            "conditions": conditions,
            "alerts": alerts,
            "overall_status": "danger" if "danger" in alerts else "warning" if "warning" in alerts else "success"
        }

    def run_web_server(self):
        """Chạy web server"""
        print("🌐 Khởi động web dashboard tại http://localhost:5001")
        self.socketio.run(self.app, host='0.0.0.0', port=5001, debug=False)

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

    def start(self):
        """Khởi động display"""
        # Kết nối MQTT
        if not self.connect():
            print("❌ Không thể kết nối đến broker")
            return

        # Chạy web server
        self.run_web_server()

    def stop(self):
        """Dừng display"""
        self.disconnect()


# Template HTML cho display web dashboard
DISPLAY_WEB_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>📊 Sensor Dashboard</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            margin: 0;
            padding: 20px;
            color: white;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 3em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
        }
        .status-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 30px;
        }
        .status-item {
            text-align: center;
        }
        .status-item h3 {
            margin: 0 0 10px 0;
            font-size: 1.2em;
        }
        .status-value {
            font-size: 1.5em;
            font-weight: bold;
        }
        .main-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
            margin-bottom: 30px;
        }
        .sensor-card {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        .sensor-icon {
            font-size: 4em;
            margin-bottom: 20px;
        }
        .sensor-value {
            font-size: 3.5em;
            font-weight: bold;
            margin: 20px 0;
        }
        .sensor-unit {
            font-size: 1.5em;
            opacity: 0.8;
        }
        .sensor-timestamp {
            font-size: 0.9em;
            opacity: 0.7;
            margin-top: 15px;
        }
        .control-panel {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 30px;
        }
        .control-panel h2 {
            text-align: center;
            margin-bottom: 20px;
        }
        .control-buttons {
            display: flex;
            justify-content: center;
            gap: 20px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 25px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            min-width: 120px;
        }
        .btn-success {
            background: linear-gradient(45deg, #4CAF50, #45a049);
            color: white;
        }
        .btn-danger {
            background: linear-gradient(45deg, #f44336, #d32f2f);
            color: white;
        }
        .btn-primary {
            background: linear-gradient(45deg, #2196F3, #1976D2);
            color: white;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }
        .conditions-panel {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 30px;
        }
        .condition-item {
            padding: 10px 20px;
            margin: 10px 0;
            border-radius: 10px;
            font-size: 1.2em;
        }
        .condition-success {
            background: rgba(76, 175, 80, 0.3);
            border-left: 4px solid #4CAF50;
        }
        .condition-warning {
            background: rgba(255, 193, 7, 0.3);
            border-left: 4px solid #FFC107;
        }
        .condition-danger {
            background: rgba(244, 67, 54, 0.3);
            border-left: 4px solid #f44336;
        }
        .status-online {
            color: #4CAF50;
        }
        .status-offline {
            color: #f44336;
        }
        .device-list {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .device-item {
            padding: 10px;
            margin: 5px 0;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .sensor-state {
            font-weight: bold;
            padding: 5px 10px;
            border-radius: 5px;
        }
        .sensor-enabled {
            background: rgba(76, 175, 80, 0.3);
            color: #4CAF50;
        }
        .sensor-disabled {
            background: rgba(244, 67, 54, 0.3);
            color: #f44336;
        }
        .last-message {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            margin-top: 20px;
        }
        .message-content {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 10px;
            padding: 15px;
            margin-top: 10px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }
        @media (max-width: 768px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
            .status-bar {
                flex-direction: column;
                gap: 20px;
            }
            .control-buttons {
                flex-direction: column;
                align-items: center;
            }
            .sensor-value {
                font-size: 2.5em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Sensor Dashboard</h1>
            <p>Real-time Temperature & Humidity Monitor</p>
        </div>
        <div class="device-list">
            <h3>📱 Connected Devices</h3>
            <div id="device-list">
                <div class="device-item">
                    <span>No devices connected</span>
                </div>
            </div>
        </div>
        
        <div class="status-bar">
            <div class="status-item">
                <h3>🔗 MQTT Status</h3>
                <div class="status-value" id="mqtt-status">❌ Disconnected</div>
            </div>
            <div class="status-item">
                <h3>⏱️ Uptime</h3>
                <div class="status-value" id="uptime">00:00:00</div>
            </div>
            <div class="status-item">
                <h3>📊 Messages</h3>
                <div class="status-value" id="message-count">0</div>
            </div>
            <div class="status-item">
                <h3>🔢 Devices</h3>
                <div class="status-value" id="device-count">0</div>
            </div>
        </div>
        
        <div class="main-grid">
            <div class="sensor-card">
                <div class="sensor-icon">🌡️</div>
                <h2>Temperature</h2>
                <div class="sensor-value" id="temperature-value">--</div>
                <div class="sensor-unit">°C</div>
                <div class="sensor-timestamp" id="temperature-time">No data</div>
            </div>
            
            <div class="sensor-card">
                <div class="sensor-icon">💧</div>
                <h2>Humidity</h2>
                <div class="sensor-value" id="humidity-value">--</div>
                <div class="sensor-unit">%</div>
                <div class="sensor-timestamp" id="humidity-time">No data</div>
            </div>
        </div>
        
        <div class="control-panel">
            <h2>🎛️ Device Control</h2>
            <div class="control-buttons">
                <button class="btn btn-success" onclick="controlDevice('enable', 'all')">
                    ✅ Enable All Sensors
                </button>
                <button class="btn btn-danger" onclick="controlDevice('disable', 'all')">
                    ❌ Disable All Sensors
                </button>
                <button class="btn btn-primary" onclick="refreshData()">
                    🔄 Refresh Data
                </button>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>📈 Avg Messages/sec</h3>
                <div class="stat-value" id="avg-msg">0.00</div>
            </div>
            <div class="stat-card">
                <h3>🕒 Last Update</h3>
                <div class="stat-value" id="last-update">Never</div>
            </div>
        </div>
        
        <div class="conditions-panel">
            <h2>🌡️💧 Environmental Conditions</h2>
            <div id="conditions-list">
                <div class="condition-item condition-warning">
                    ⏳ Waiting for sensor data...
                </div>
            </div>
        </div>
        
        
        
        <div class="last-message">
            <h3>📨 Last Message</h3>
            <div class="message-content" id="last-message-content">
                Waiting for messages...
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        
        socket.on('connect', function() {
            console.log('Connected to dashboard server');
        });
        
        socket.on('status_update', function(data) {
            updateStatus(data);
        });
        
        socket.on('data_update', function(data) {
            updateSensorData(data);
        });
        
        socket.on('device_update', function(data) {
            updateDeviceList(data);
        });
        
        socket.on('mqtt_status', function(data) {
            updateMQTTStatus(data.connected);
        });
        
        function updateStatus(data) {
            updateMQTTStatus(data.mqtt_connected);
            updateSensorData(data);
            updateStatistics(data.stats);
        }
        
        function updateMQTTStatus(connected) {
            const mqttStatus = document.getElementById('mqtt-status');
            if (connected) {
                mqttStatus.innerHTML = '✅ Connected';
                mqttStatus.className = 'status-value status-online';
            } else {
                mqttStatus.innerHTML = '❌ Disconnected';
                mqttStatus.className = 'status-value status-offline';
            }
        }
        
        function updateSensorData(data) {
            if (data.sensor_data || data.data) {
                const sensorData = data.sensor_data || data.data;
                
                // Update temperature
                if (sensorData.temperature) {
                    document.getElementById('temperature-value').textContent = 
                        sensorData.temperature.value || sensorData.temperature;
                    if (sensorData.temperature.timestamp) {
                        document.getElementById('temperature-time').textContent = 
                            new Date(sensorData.temperature.timestamp).toLocaleString();
                    }
                }
                
                // Update humidity
                if (sensorData.humidity) {
                    document.getElementById('humidity-value').textContent = 
                        sensorData.humidity.value || sensorData.humidity;
                    if (sensorData.humidity.timestamp) {
                        document.getElementById('humidity-time').textContent = 
                            new Date(sensorData.humidity.timestamp).toLocaleString();
                    }
                }
                
                // Update last update time
                if (sensorData.last_update) {
                    document.getElementById('last-update').textContent = 
                        new Date(sensorData.last_update).toLocaleTimeString();
                }
                
                // Update environmental conditions
                updateConditions(sensorData);
                
                // Update device list with sensor states
                updateDeviceList(sensorData);
            }
            
            // Update last message
            if (data.topic && data.data) {
                document.getElementById('last-message-content').innerHTML = 
                    `<strong>Topic:</strong> ${data.topic}<br>` +
                    `<strong>Data:</strong> ${JSON.stringify(data.data, null, 2)}`;
            }
        }
        
        function updateStatistics(stats) {
            if (stats) {
                document.getElementById('uptime').textContent = stats.uptime || '00:00:00';
                document.getElementById('message-count').textContent = stats.message_count || 0;
                document.getElementById('device-count').textContent = stats.connected_devices || 0;
                document.getElementById('avg-msg').textContent = stats.avg_msg_per_sec || '0.00';
                
                // Device list is updated in updateDeviceList
            }
        }
        
        function updateDeviceList(sensorData) {
            const deviceListEl = document.getElementById('device-list');
            if (sensorData.sensor_states && Object.keys(sensorData.sensor_states).length > 0) {
                
                deviceListEl.innerHTML = Object.entries(sensorData.sensor_states).map(([device, state]) => 
                    `<div class="device-item">
                        <span>📱 ${device}</span>
                        <span class="sensor-state ${state ? 'sensor-enabled' : 'sensor-disabled'}">
                            ${state ? '▶️ Enabled' : '⏸️ Disabled'}
                        </span>
                        <button class="btn btn-danger" onclick="controlDevice('${state ? 'disable' : 'enable'}', '${device}')">${state ? 'Enabled' : 'Disabled'}</button>
                    </div>`
                ).join('');
            } else {
                deviceListEl.innerHTML = '<div class="device-item"><span>No devices connected</span></div>';
            }
        }
        
        function updateConditions(sensorData) {
            const conditionsEl = document.getElementById('conditions-list');
            
            if (sensorData.temperature && sensorData.humidity) {
                const temp = sensorData.temperature.value || sensorData.temperature;
                const humidity = sensorData.humidity.value || sensorData.humidity;
                
                const conditions = evaluateConditions(temp, humidity);
                
                conditionsEl.innerHTML = conditions.map(condition => 
                    `<div class="condition-item condition-${condition.type}">
                        ${condition.message}
                    </div>`
                ).join('');
            }
        }
        
        function evaluateConditions(temperature, humidity) {
            const conditions = [];
            
            // Temperature conditions
            if (temperature < 18) {
                conditions.push({type: 'warning', message: '🥶 Temperature too cold'});
            } else if (temperature > 32) {
                conditions.push({type: 'danger', message: '🥵 Temperature too hot'});
            } else if (temperature >= 20 && temperature <= 26) {
                conditions.push({type: 'success', message: '😊 Temperature comfortable'});
            }
            
            // Humidity conditions
            if (humidity < 40) {
                conditions.push({type: 'warning', message: '🏜️ Air too dry'});
            } else if (humidity > 70) {
                conditions.push({type: 'warning', message: '🌊 Air too humid'});
            } else if (humidity >= 50 && humidity <= 60) {
                conditions.push({type: 'success', message: '😊 Humidity comfortable'});
            }
            
            if (conditions.length === 0) {
                conditions.push({type: 'warning', message: '⚠️ Environment needs attention'});
            }
            
            return conditions;
        }
        
        function controlDevice(command, deviceId) {
            console.log(command)
            socket.emit('control_device', {
                command: command,
                device_id: deviceId
            });
            console.log(`Sent ${command} command to ${deviceId}`);
        }
        
        function refreshData() {
            socket.emit('get_status');
        }
        
        // Auto-refresh every 30 seconds
        setInterval(refreshData, 30000);
        
        // Initial load
        refreshData();
    </script>
</body>
</html>
"""


def main():
    """Hàm main"""
    print("📊 MQTT Sensor Dashboard với Web Interface")
    print("=" * 60)

    # Cấu hình kết nối
    BROKER_HOST = "localhost"
    BROKER_PORT = 1883
    USERNAME = "nhandev"
    PASSWORD = "123456aA@"
    CLIENT_ID = "sensor_display_001"

    # Tạo display
    display = SensorDataDisplay(
        broker_host=BROKER_HOST,
        broker_port=BROKER_PORT,
        username=USERNAME,
        password=PASSWORD,
        client_id=CLIENT_ID
    )

    try:
        display.start()
    except KeyboardInterrupt:
        print("\n⏹️  Dừng dashboard...")
        display.stop()
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        display.stop()


if __name__ == "__main__":
    main()
