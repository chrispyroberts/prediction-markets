import socketio

# Create a Socket.IO client
sio = socketio.Client()

@sio.event
def connect():
    print("✅ Connected to WebSocket server.")
    print(f"🔗 Connection SID:     {sio.sid}")
    print(f"🚚 Transport:          {sio.transport()}")
    print(f"🌐 Connected URL:      {sio.connection_url}")

@sio.event
def disconnect():
    print("❌ Disconnected from WebSocket server.")

@sio.event
def price_update(data):
    print("📈 Received price update:")
    print(f"   Price:          {data['brti']}")
    print(f"   Simple Average: {data['simple_average']}")
    print(f"   Timestamp:      {data['timestamp']}")

if __name__ == "__main__":
    try:
        print("🔌 Connecting to WebSocket server...")
        sio.connect("http://localhost:5000", namespaces=["/"])
        sio.wait()
    except Exception as e:
        print("⚠️ Connection error:", e)
