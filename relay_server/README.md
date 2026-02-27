# Relay Server

Servidor relay UDP para multijugador por internet.

## Requisitos

- Python 3.8+ (solo stdlib, sin dependencias)
- Puerto UDP abierto (default: 7777)

## Ejecución

```bash
python relay_server.py --port 7777
```

## Deploy en VPS

```bash
# Copiar solo este archivo al VPS
scp relay_server.py user@vps:/opt/relay/

# Ejecutar con nohup
ssh user@vps "cd /opt/relay && nohup python3 relay_server.py --port 7777 > relay.log 2>&1 &"
```

## Firewall

Abrir puerto UDP:
```bash
# UFW (Ubuntu)
sudo ufw allow 7777/udp

# iptables
sudo iptables -A INPUT -p udp --dport 7777 -j ACCEPT
```

## Systemd (opcional)

```ini
[Unit]
Description=Racing Game Relay Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/relay/relay_server.py --port 7777
Restart=always
User=relay

[Install]
WantedBy=multi-user.target
```
