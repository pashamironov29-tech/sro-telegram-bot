#!/bin/bash
# Hardening VPS for SRO bot — run once as root
set -euo pipefail

ADMIN_IP="${1:-82.204.178.85}"
APP_DIR="/opt/sro-bot"

echo "==> SSH: key-only (drop-in)"
install -d -m 755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-sro-hardening.conf << 'EOF'
# SRO bot VPS hardening
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
MaxAuthTries 5
EOF
sshd -t
systemctl reload sshd
echo "SSH reloaded OK"

echo "==> UFW (SSH from ${ADMIN_IP} only)"
apt-get install -y ufw >/dev/null 2>&1 || true
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow from "${ADMIN_IP}" to any port 22 proto tcp comment 'SSH Pasha'
ufw --force enable
ufw status verbose

echo "==> config_keys permissions"
if [ -f "$APP_DIR/config_keys.py" ]; then
  chown srobot:srobot "$APP_DIR/config_keys.py"
  chmod 600 "$APP_DIR/config_keys.py"
  stat -c '%a %U:%G %n' "$APP_DIR/config_keys.py"
fi

echo "==> fail2ban for ssh"
apt-get install -y fail2ban >/dev/null 2>&1 || true
cat > /etc/fail2ban/jail.d/sshd.local << 'EOF'
[sshd]
enabled = true
port = ssh
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl enable fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban
systemctl is-active fail2ban

echo "==> DONE"
