#!/usr/bin/env bash
# =============================================================================
#  setup-kali.sh  —  Cài đặt môi trường trên Kali Linux cho dự án IoT Blockchain
#  Chạy với quyền root hoặc sudo:  sudo bash setup-kali.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*"; }
info()  { echo -e "${CYAN}[i]${NC} $*"; }

echo ""
echo "=============================================="
echo "  IoT Blockchain Demo — Kali Linux Setup"
echo "=============================================="
echo ""

# ---------------------------------------------------
# 1. Cập nhật hệ thống
# ---------------------------------------------------
info "Cập nhật hệ thống..."
apt-get update -y && apt-get upgrade -y
log "Hệ thống đã được cập nhật"

# ---------------------------------------------------
# 2. Cài đặt Docker
# ---------------------------------------------------
if command -v docker &>/dev/null; then
    log "Docker đã được cài đặt: $(docker --version)"
else
    info "Cài đặt Docker..."
    apt-get install -y docker.io
    systemctl enable docker
    systemctl start docker
    log "Docker đã cài xong: $(docker --version)"
fi

# ---------------------------------------------------
# 3. Cài đặt Docker Compose
# ---------------------------------------------------
if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
    log "Docker Compose đã được cài đặt"
else
    info "Cài đặt Docker Compose plugin..."
    apt-get install -y docker-compose-plugin 2>/dev/null || {
        warn "Cài plugin thất bại, thử cài docker-compose standalone..."
        apt-get install -y docker-compose
    }
    log "Docker Compose đã cài xong"
fi

# ---------------------------------------------------
# 4. Thêm user hiện tại vào group docker (không cần sudo)
# ---------------------------------------------------
REAL_USER="${SUDO_USER:-$USER}"
if id -nG "$REAL_USER" | grep -qw docker; then
    log "User '$REAL_USER' đã trong group docker"
else
    info "Thêm user '$REAL_USER' vào group docker..."
    usermod -aG docker "$REAL_USER"
    log "Đã thêm. Cần đăng xuất/đăng nhập lại hoặc chạy: newgrp docker"
fi

# ---------------------------------------------------
# 5. Cài đặt các tool phụ trợ
# ---------------------------------------------------
info "Cài đặt các tool phụ trợ (curl, jq, git)..."
apt-get install -y curl jq git
log "Các tool phụ trợ đã cài xong"

# ---------------------------------------------------
# 6. Cài đặt Hyperledger Fabric (tùy chọn)
# ---------------------------------------------------
echo ""
read -p "Bạn có muốn cài Hyperledger Fabric samples? (y/N): " INSTALL_FABRIC
if [[ "${INSTALL_FABRIC,,}" == "y" ]]; then
    info "Cài đặt Hyperledger Fabric samples..."
    
    # Cài Go (yêu cầu bởi Fabric)
    if ! command -v go &>/dev/null; then
        info "Cài đặt Go..."
        apt-get install -y golang
        log "Go đã cài xong: $(go version)"
    fi

    FABRIC_DIR="$HOME/fabric-samples"
    if [ -d "$FABRIC_DIR" ]; then
        warn "Thư mục $FABRIC_DIR đã tồn tại, bỏ qua tải về."
    else
        cd "$HOME"
        curl -sSLO https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh
        chmod +x install-fabric.sh
        ./install-fabric.sh docker samples binary
        log "Fabric samples đã tải về $FABRIC_DIR"
    fi

    # Khởi tạo test-network
    echo ""
    read -p "Bạn có muốn khởi tạo test-network ngay bây giờ? (y/N): " START_NETWORK
    if [[ "${START_NETWORK,,}" == "y" ]]; then
        cd "$FABRIC_DIR/test-network"
        info "Dừng network cũ (nếu có)..."
        ./network.sh down 2>/dev/null || true
        info "Khởi tạo network mới với channel 'mychannel'..."
        ./network.sh up createChannel -c mychannel -ca
        log "Test network đã khởi tạo xong!"
        
        echo ""
        read -p "Bạn có muốn deploy chaincode 'iotcc'? (y/N): " DEPLOY_CC
        if [[ "${DEPLOY_CC,,}" == "y" ]]; then
            warn "Bạn cần có chaincode iotcc trong thư mục phù hợp."
            warn "Ví dụ: $FABRIC_DIR/chaincode/iotcc/"
            info "Vui lòng deploy chaincode thủ công theo hướng dẫn trong README."
        fi
    fi
else
    info "Bỏ qua cài đặt Fabric. Bạn có thể chạy ở chế độ standalone."
fi

# ---------------------------------------------------
# 7. Tóm tắt
# ---------------------------------------------------
echo ""
echo "=============================================="
echo "  Cài đặt hoàn tất!"
echo "=============================================="
echo ""
log "Docker:          $(docker --version 2>/dev/null || echo 'N/A')"
log "Docker Compose:  $(docker compose version 2>/dev/null || docker-compose --version 2>/dev/null || echo 'N/A')"
echo ""
info "Các bước tiếp theo:"
echo "  1. cd vào thư mục dự án"
echo "  2. Chế độ STANDALONE (không cần Fabric):"
echo "     docker compose -f docker-compose.standalone.yml up --build"
echo "  3. Chế độ ĐẦY ĐỦ (với Fabric đã cài):"
echo "     docker compose up --build"
echo "  4. Mở trình duyệt: http://localhost:8000"
echo "  5. API docs: http://localhost:8000/docs"
echo ""
warn "Nếu bạn mới thêm vào group docker, hãy đăng xuất rồi đăng nhập lại!"
echo ""
