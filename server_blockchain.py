from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
import json
import os
import hashlib
import subprocess
import threading
import time

# --- Fabric toggle ---
FABRIC_ENABLED = os.environ.get("FABRIC_ENABLED", "true").lower() == "true"


_payload_lock = threading.Lock()

# --- Batch config ---
BATCH_SIZE = 10       # gửi lên Fabric khi đủ N bản ghi
BATCH_INTERVAL = 5.0  # hoặc sau N giây dù chưa đủ

_batch_buffer: list = []
_batch_lock = threading.Lock()


def _flush_batch(records: list):
    """Gửi đồng thời tất cả record trong batch lên Fabric, cập nhật file 1 lần."""
    if not FABRIC_ENABLED:
        return
    results = {}

    def _invoke_one(record):
        try:
            code, _, _ = invoke_fabric(
                record["reading_id"], record["device_id"],
                record["payload_hash"], record["timestamp"]
            )
            results[record["reading_id"]] = "COMMITTED" if code == 0 else "FABRIC_FAILED"
        except subprocess.TimeoutExpired:
            results[record["reading_id"]] = "FABRIC_TIMEOUT"

    threads = [threading.Thread(target=_invoke_one, args=(r,), daemon=True) for r in records]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Cập nhật file 1 lần duy nhất sau khi tất cả invoke xong
    with _payload_lock:
        payloads = load_payloads()
        for p in payloads:
            if p["reading_id"] in results:
                p["status"] = results[p["reading_id"]]
        save_payloads(payloads)


def _batch_worker():
    """Background thread: flush buffer mỗi BATCH_INTERVAL giây."""
    while True:
        time.sleep(BATCH_INTERVAL)
        with _batch_lock:
            if not _batch_buffer:
                continue
            to_flush = _batch_buffer.copy()
            _batch_buffer.clear()
        _flush_batch(to_flush)


threading.Thread(target=_batch_worker, daemon=True).start()


def _get_fabric_env():
    home = os.path.expanduser("~")
    env = os.environ.copy()
    env["PATH"] = f"{home}/fabric-samples/bin:" + env.get("PATH", "")
    env["FABRIC_CFG_PATH"] = f"{home}/fabric-samples/config"
    env["CORE_PEER_TLS_ENABLED"] = "true"
    env["CORE_PEER_LOCALMSPID"] = "Org1MSP"
    env["CORE_PEER_MSPCONFIGPATH"] = (
        f"{home}/fabric-samples/test-network/organizations/peerOrganizations"
        f"/org1.example.com/users/Admin@org1.example.com/msp"
    )
    env["CORE_PEER_ADDRESS"] = "localhost:7051"
    env["CORE_PEER_TLS_ROOTCERT_FILE"] = (
        f"{home}/fabric-samples/test-network/organizations/peerOrganizations"
        f"/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
    )
    return env, home


def invoke_fabric(reading_id, device_id, payload_hash, timestamp):
    env, home = _get_fabric_env()
    fabric_host = os.environ.get("FABRIC_HOST", "localhost")
    chaincode_args = json.dumps({
        "function": "CreateRecord",
        "Args": [reading_id, device_id, payload_hash, timestamp]
    })
    cmd = [
        "peer", "chaincode", "invoke",
        "-o", f"{fabric_host}:7050",
        "--ordererTLSHostnameOverride", "orderer.example.com",
        "--tls",
        "--cafile", (
            f"{home}/fabric-samples/test-network/organizations/ordererOrganizations"
            f"/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
        ),
        "-C", "mychannel",
        "-n", "iotcc",
        "--peerAddresses", f"{fabric_host}:7051",
        "--tlsRootCertFiles", (
            f"{home}/fabric-samples/test-network/organizations/peerOrganizations"
            f"/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
        ),
        "--peerAddresses", f"{fabric_host}:9051",
        "--tlsRootCertFiles", (
            f"{home}/fabric-samples/test-network/organizations/peerOrganizations"
            f"/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"
        ),
        "-c", chaincode_args
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    return result.returncode, result.stdout, result.stderr


def query_fabric(reading_id):
    env, _ = _get_fabric_env()
    chaincode_args = json.dumps({
        "function": "ReadRecord",
        "Args": [reading_id]
    })
    cmd = [
        "peer", "chaincode", "query",
        "-C", "mychannel",
        "-n", "iotcc",
        "-c", chaincode_args
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=15)
    return result.returncode, result.stdout, result.stderr


app = FastAPI(title="IoT Demo With Hyperledger Fabric")

PAYLOAD_FILE = "iot_payloads.json"


class SensorData(BaseModel):
    device_id: str
    temperature: float
    humidity: float


class UpdateSensorData(BaseModel):
    temperature: float | None = None
    humidity: float | None = None


def load_json_file(file_path: str):
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_json_file(file_path: str, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def calculate_hash(data: dict) -> str:
    data_string = json.dumps(data, sort_keys=True)
    return hashlib.sha256(data_string.encode()).hexdigest()


def load_payloads():
    return load_json_file(PAYLOAD_FILE)


def save_payloads(payloads):
    save_json_file(PAYLOAD_FILE, payloads)


def build_record(sensor_data: SensorData):
    timestamp = datetime.now(timezone.utc).isoformat()

    payload = {
        "device_id": sensor_data.device_id,
        "temperature": sensor_data.temperature,
        "humidity": sensor_data.humidity,
        "timestamp": timestamp
    }

    payload_hash = calculate_hash(payload)

    record = {
        "reading_id": f"{sensor_data.device_id}_{timestamp}",
        "device_id": sensor_data.device_id,
        "timestamp": timestamp,
        "payload": payload,
        "payload_hash": payload_hash,
        "status": "PENDING"
    }

    return record


@app.get("/")
def root():
    return {"message": "IoT demo with Hyperledger Fabric is running"}


@app.post("/data")
def receive_data(data: SensorData):
    record = build_record(data)

    with _payload_lock:
        payloads = load_payloads()
        payloads.append(record)
        save_payloads(payloads)

    flush_now = False
    with _batch_lock:
        _batch_buffer.append(record)
        if len(_batch_buffer) >= BATCH_SIZE:
            to_flush = _batch_buffer.copy()
            _batch_buffer.clear()
            flush_now = True

    if flush_now:
        threading.Thread(target=_flush_batch, args=(to_flush,), daemon=True).start()

    return {
        "status": "accepted",
        "message": f"Payload đã lưu off-chain, sẽ commit lên Fabric trong tối đa {BATCH_INTERVAL}s",
        "record": {
            "reading_id": record["reading_id"],
            "device_id": record["device_id"],
            "timestamp": record["timestamp"],
            "payload_hash": record["payload_hash"],
            "status": "PENDING"
        }
    }


@app.get("/data")
def get_data():
    payloads = load_payloads()
    return [{"index": i, **record} for i, record in enumerate(payloads)]


@app.get("/verify-local")
def verify_local():
    payloads = load_payloads()
    invalid_records = []
    valid_count = 0

    for i, record in enumerate(payloads):
        recalculated_hash = calculate_hash(record["payload"])
        if recalculated_hash != record["payload_hash"]:
            invalid_records.append({
                "index": i,
                "reading_id": record["reading_id"],
                "device_id": record["device_id"],
                "timestamp": record["timestamp"],
                "status": record["status"],
                "payload_hien_tai": record["payload"],
                "hash_hien_tai": recalculated_hash,
                "hash_goc": record["payload_hash"],
                "canh_bao": f"Ban ghi index {i} ({record['device_id']}) da bi sua!"
            })
        else:
            valid_count += 1

    if invalid_records:
        return {
            "valid": False,
            "tong_ban_ghi": len(payloads),
            "ban_ghi_hop_le": valid_count,
            "ban_ghi_bi_sua": len(invalid_records),
            "message": f"Phat hien {len(invalid_records)} ban ghi bi gia mao!",
            "chi_tiet": invalid_records
        }

    return {
        "valid": True,
        "tong_ban_ghi": len(payloads),
        "ban_ghi_hop_le": valid_count,
        "message": "Tat ca payload off-chain deu khop hash, khong co du lieu bi sua"
    }


@app.get("/verify-fabric")
def verify_fabric():
    payloads = load_payloads()
    skipped = []

    committed = [(i, r) for i, r in enumerate(payloads) if r["status"] == "COMMITTED"]
    pending   = [(i, r) for i, r in enumerate(payloads) if r["status"] != "COMMITTED"]

    for i, record in pending:
        skipped.append({
            "index": i,
            "reading_id": record["reading_id"],
            "status": record["status"],
            "message": "Bỏ qua — chưa được commit lên Fabric"
        })

    def _query_one(i, record):
        current_hash = calculate_hash(record["payload"])
        try:
            code, out, err = query_fabric(record["reading_id"])
        except subprocess.TimeoutExpired:
            return {
                "index": i, "reading_id": record["reading_id"],
                "device_id": record["device_id"], "status": record["status"],
                "valid": False, "message": "Timeout khi query Fabric"
            }

        if code != 0:
            return {
                "index": i, "reading_id": record["reading_id"],
                "device_id": record["device_id"], "status": record["status"],
                "valid": False, "error": err,
                "message": "Không query được hash từ Fabric"
            }
        try:
            fabric_hash = json.loads(out)["payload_hash"]
        except Exception:
            return {
                "index": i, "reading_id": record["reading_id"],
                "device_id": record["device_id"], "status": record["status"],
                "valid": False, "raw_fabric_response": out,
                "message": "Không đọc được dữ liệu trả về từ Fabric"
            }
        return {
            "index": i, "reading_id": record["reading_id"],
            "device_id": record["device_id"], "status": record["status"],
            "current_hash": current_hash, "fabric_hash": fabric_hash,
            "valid": current_hash == fabric_hash
        }

    query_results = [None] * len(committed)
    threads = [
        threading.Thread(target=lambda idx, item: query_results.__setitem__(idx, _query_one(*item)),
                         args=(idx, item), daemon=True)
        for idx, item in enumerate(committed)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    results = query_results
    invalid = [r for r in results if r and not r["valid"]]

    if not committed:
        return {
            "valid": None,
            "tong_ban_ghi": len(payloads),
            "da_kiem_tra": 0,
            "bo_qua_pending": len(skipped),
            "message": "Chưa có bản ghi nào được commit lên Fabric để kiểm tra",
            "pending": skipped
        }

    return {
        "valid": len(invalid) == 0,
        "tong_ban_ghi": len(payloads),
        "da_kiem_tra": len(results),
        "bo_qua_pending": len(skipped),
        "ban_ghi_hop_le": len(results) - len(invalid),
        "ban_ghi_bi_sua": len(invalid),
        "message": "Kiểm tra hash bằng Hyperledger Fabric thật",
        "chi_tiet": results,
        "pending": skipped
    }


@app.get("/data/{index}")
def get_data_by_index(index: int):
    payloads = load_payloads()
    if index < 0 or index >= len(payloads):
        raise HTTPException(status_code=404, detail="Index không hợp lệ")

    return {
        "index": index,
        "full_record": payloads[index],
        "payload_to_edit": {
            "temperature": payloads[index]["payload"]["temperature"],
            "humidity": payloads[index]["payload"]["humidity"]
        }
    }


@app.put("/data/update/{index}")
def update_data(index: int, update: UpdateSensorData):
    with _payload_lock:
        payloads = load_payloads()

        if index < 0 or index >= len(payloads):
            raise HTTPException(status_code=404, detail="Index không hợp lệ")

        old_payload = payloads[index]["payload"].copy()
        old_timestamp = payloads[index]["timestamp"]
        old_hash = payloads[index]["payload_hash"]

        record = payloads[index]
        changes = []
        new_timestamp = datetime.now(timezone.utc).isoformat()
        updated = False

        if update.temperature is not None:
            changes.append(f"temperature: {old_payload['temperature']} → {update.temperature}")
            record["payload"]["temperature"] = update.temperature
            updated = True

        if update.humidity is not None:
            changes.append(f"humidity: {old_payload['humidity']} → {update.humidity}")
            record["payload"]["humidity"] = update.humidity
            updated = True

        if updated:
            record["timestamp"] = new_timestamp
            record["payload"]["timestamp"] = new_timestamp
            changes.append(f"timestamp: {old_timestamp} → {new_timestamp} (tự động)")

        if not updated:
            return {
                "message": "Không có trường nào được cập nhật",
                "record": record["payload"]
            }

        new_hash = calculate_hash(record["payload"])
        record["payload_hash"] = new_hash
        save_payloads(payloads)

    return {
        "message": f"Đã cập nhật index {index}",
        "old_payload": old_payload,
        "new_payload": record["payload"],
        "changes": changes,
        "hash_analysis": {
            "old_hash": old_hash,
            "new_hash": new_hash,
            "changed": old_hash != new_hash
        }
    }


@app.delete("/reset")
def reset_all():
    with _batch_lock:
        _batch_buffer.clear()
    with _payload_lock:
        save_payloads([])

    return {
        "message": "Đã reset toàn bộ dữ liệu off-chain"
    }
