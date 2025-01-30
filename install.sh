#!/bin/bash

# Check if "script.env" exists
# Get the directory of the current script
SCRIPT_DIR="$(pwd)"
SCRIPT_ENV_PATH="${SCRIPT_DIR}/script.env"

# Validate env exists before install services
if [ ! -f "$SCRIPT_ENV_PATH" ]; then
    echo "File 'script.env' does not exist in the same folder."
    exit 0
fi

# Install python3
DEBIAN_FRONTEND=noninteractive sudo apt-get install -y python3 python3-full python3-pip

# Create env
python3 -m venv .env
PY3="${SCRIPT_DIR}/.env/bin/python3"

# Install python packages
$PY3 -m pip install -U pip setuptools
$PY3 -m pip install -r requirements.txt

# Create updater service
UPDATER_SERVICE_NAME="vpn_status_updater.service"
UPDATER_SERVICE_PATH="/etc/systemd/system/${UPDATER_SERVICE_NAME}"
UPDATER_PY_SCRIPT="${SCRIPT_DIR}/status_updater.py"

sudo systemctl stop "${UPDATER_SERVICE_NAME}" 2>/dev/null
sudo systemctl disable "${UPDATER_SERVICE_NAME}" 2>/dev/null

cat <<EOF | sudo tee "${UPDATER_SERVICE_PATH}" > /dev/null
[Unit]
Description=OpenVPN Wireguard Updater
After=network.target

[Service]
ExecStart=${PY3} ${UPDATER_PY_SCRIPT}
WorkingDirectory=${SCRIPT_DIR}
User=root
EOF

# Create timer service
TIMER_SERVICE_NAME="vpn_status_updater.timer"
TIMER_SERVICE_PATH="/etc/systemd/system/${TIMER_SERVICE_NAME}"

sudo systemctl stop "${TIMER_SERVICE_NAME}" 2>/dev/null
sudo systemctl disable "${TIMER_SERVICE_NAME}" 2>/dev/null

cat <<EOF | sudo tee "${TIMER_SERVICE_PATH}" > /dev/null
[Unit]
Description=Execute Updater periodic

[Timer]
OnBootSec=5s
OnUnitActiveSec=5s
Unit=${UPDATER_SERVICE_NAME}

[Install]
WantedBy=timers.target
EOF

# Reload systemd to register the new service
sudo systemctl daemon-reload

# Optionally enable the service to start on boot
sudo systemctl enable --now $TIMER_SERVICE_NAME
