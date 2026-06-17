#!/bin/bash
# Kali Agent Setup - Auto-start + disable sleep

echo "[+] Configuration de l'agent Kali..."

# === Disable sleep/suspend ===
echo "[+] Désactivation de la veille et suspension..."

# Disable suspend on AC
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null

# Disable lid close action
if [ -f /etc/systemd/logind.conf ]; then
    sudo sed -i 's/^#HandleLidSwitch=.*/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
    sudo sed -i 's/^HandleLidSwitch=.*/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
    sudo sed -i 's/^#HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
    sudo sed -i 's/^HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
    sudo systemctl restart systemd-logind
fi

# Disable screen blanking
gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
gsettings set org.gnome.desktop.screensaver idle-activation-enabled false 2>/dev/null
gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null

# Disable DPMS (Display Power Management Signaling)
xset s off -dpms 2>/dev/null

# Disable grub deep sleep
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="quiet acpi=off noapic"/' /etc/default/grub 2>/dev/null
sudo update-grub 2>/dev/null

# === Install dependencies ===
echo "[+] Installation des dépendances..."
sudo apt update -y
sudo apt install -y python3 python3-pip imagemagick x11-utils xdotool

# Install Python packages
pip3 install flask flask-socketio requests pillow opencv-python mss pyngrok 2>/dev/null

# Ensure ngrok is installed
if ! command -v ngrok &>/dev/null; then
    echo "[+] Installation de ngrok..."
    wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
    tar xzf ngrok-v3-stable-linux-amd64.tgz
    sudo mv ngrok /usr/local/bin/
    rm ngrok-v3-stable-linux-amd64.tgz
fi

# === Create agent service ===
echo "[+] Création du service systemd..."
cat << EOF | sudo tee /etc/systemd/system/kali-agent.service > /dev/null
[Unit]
Description=Kali Agent - Remote Control Panel
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$(pwd)
Environment=DISPLAY=:0
Environment=XAUTHORITY=$HOME/.Xauthority
ExecStart=/usr/bin/python3 $(pwd)/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable kali-agent.service

echo ""
echo "[✔] Installation terminée !"
echo ""
echo "Commandes:"
echo "  sudo systemctl start kali-agent   # Lancer maintenant"
echo "  sudo systemctl stop kali-agent    # Arrêter"
echo "  sudo journalctl -u kali-agent -f  # Voir les logs"
echo ""
echo "Le panel sera accessible via le lien envoyé sur Discord."
echo "Mot de passe par défaut: kali"
echo ""
