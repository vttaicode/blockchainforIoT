import requests
import random
import time
import os
from datetime import datetime

URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8000/data")
DEVICE_ID = os.environ.get("DEVICE_ID", "sensor_1")

while True:
    data = {
        "device_id": DEVICE_ID,
        "temperature": round(random.uniform(20, 30), 2),
        "humidity": round(random.uniform(40, 60), 2)
    }

    try:
        response = requests.post(URL, json=data)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent:", data, "| Status:", response.status_code)
    except Exception as e:
        print("Error:", e)

    time.sleep(10)
