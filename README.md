# Bounce Bridge

Email bounce notification bridge for AWS SES, Postal, and Postfix. Processes bounces, manages Postal suppressions via direct MariaDB access, and notifies agents in Chatwoot.

**Live at:** `https://bounce-bridge.fiszu.com` (CT176)

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│  AWS SES     │   │  Postal      │   │  Postfix         │
│  (SNS/n8n)   │   │  (Webhook)   │   │  (bounce-monitor)│
└──────┬───────┘   └──────┬───────┘   └────────┬─────────┘
       │                  │                     │
       ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────┐
│  Bounce Bridge (CT176)  — FastAPI + uvicorn             │
│                                                         │
│  /api/v1/ses-bounce     → process bounce                │
│  /api/v1/postal-bounce  → process bounce OR held msg    │
│  /api/v1/postfix-bounce → process bounce                │
│                                                         │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐ │
│  │ SQLite DB    │  │ Postal MariaDB│  │ Chatwoot API │ │
│  │ (local)      │  │ (SSH tunnel)  │  │              │ │
│  └──────────────┘  └───────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Multi-source bounce processing**: SES (SNS), Postal (webhook), Postfix (DSN)
- **Postal suppression management**: Direct MariaDB insert via SSH tunnel (no API)
- **Chatwoot integration**: Private notes on bounce and suppressed-send events
- **Suppressed recipient alerts**: When Postal holds a message due to suppression, notifies the assigned Chatwoot agent with reason and recommendation
- **Duplicate detection**: Per-recipient dedup within 24-hour window
- **Sender notifications**: Email notification to original sender on bounce
- **SNS SubscriptionConfirmation**: Auto-confirms AWS SNS subscriptions

## Webhook Endpoints

| Source | Endpoint | Events Handled |
|--------|----------|----------------|
| AWS SES | `POST /api/v1/ses-bounce` | Bounce, Complaint, SubscriptionConfirmation |
| Postal | `POST /api/v1/postal-bounce` | MessageBounced, MessageDeliveryFailed, MessageHeld |
| Postfix | `POST /api/v1/postfix-bounce` | Hard bounce (5.x.x), Soft bounce (4.x.x) |
| Health | `GET /api/v1/health` | Service health check |

## Suppression Expiry

| Source | Type | Expiry |
|--------|------|--------|
| AWS SES | Permanent Bounce | 365 days |
| AWS SES | Transient Bounce | 30 days |
| AWS SES | Complaint | 180 days |
| Postal | Any Bounce | 30 days |
| Postfix | Hard (5.x.x) | 365 days |
| Postfix | Soft (4.x.x) | 30 days |

## Postal Webhook Setup

### Required Configuration in Postal UI

1. Navigate to: `https://postal.voltnation.pl/org/esc/servers/postal001/webhooks`

2. If a webhook already exists for bounce-bridge, click to edit it.
   If not, click **"Add Webhook"**.

3. Configure:
   - **URL:** `https://bounce-bridge.fiszu.com/api/v1/postal-bounce`
   - **Events — check all three:**
     - `MessageBounced` — email permanently rejected
     - `MessageDeliveryFailed` — delivery attempt failed
     - `MessageHeld` — email held (suppression, policy, etc.)

4. Save.

### How MessageHeld Works

When Postal holds a message because the recipient is on the suppression list:

1. Postal fires `MessageHeld` webhook to bounce-bridge
2. Bounce-bridge detects "suppression" in the hold details
3. Looks up the suppression record from Postal MariaDB (type, reason, dates)
4. Extracts Chatwoot conversation ID from message headers
5. Posts a private note to the Chatwoot conversation explaining:
   - Why the email was blocked (Hard Bounce / Complaint / Temporary)
   - When the address was suppressed and until when
   - Recommendation to contact the customer by phone
   - @mentions the assigned agent
6. Logs the blocked attempt to the local SQLite database

If no Chatwoot conversation ID is found in the message headers, the blocked attempt is still logged but no Chatwoot notification is sent.

## MariaDB Access (Postal Suppressions)

Bounce-bridge inserts suppressions directly into Postal's MariaDB via SSH tunnel. The database is **never exposed on any network interface**.

```
CT176 (bounce-bridge)
  127.0.0.1:3307  ──SSH tunnel──>  CT200 127.0.0.1:3306 (MariaDB)
```

The tunnel is managed by systemd: `mariadb-tunnel.service`
See: [eMobility-Innovations/mariadb-ssh-proxy](https://github.com/eMobility-Innovations/mariadb-ssh-proxy)

## Installation

### On CT176

```bash
# Clone
git clone https://github.com/eMobility-Innovations/bounce-bridge.git /opt/bounce-bridge
cd /opt/bounce-bridge

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — set API keys, DB credentials
mkdir -p data

# Install and start
cp bounce-bridge.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bounce-bridge
systemctl start bounce-bridge
```

### SSH Tunnel (required for Postal suppression)

```bash
# Install tunnel service (see mariadb-ssh-proxy repo)
# Or manually:
cat > /etc/systemd/system/mariadb-tunnel.service << 'EOF'
[Unit]
Description=SSH tunnel to Postal MariaDB on CT200
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/ssh -N -L 127.0.0.1:3307:127.0.0.1:3306 root@192.168.103.200 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl enable mariadb-tunnel
systemctl start mariadb-tunnel
```

## Configuration

### Environment Variables (.env)

```env
# Postal API (for message lookup)
POSTAL_API_KEY=your-postal-api-key
POSTAL_API_URL=https://postal.voltnation.pl

# Postal MariaDB via SSH tunnel (for suppressions)
POSTAL_DB_HOST=127.0.0.1
POSTAL_DB_PORT=3307
POSTAL_DB_USER=root
POSTAL_DB_PASSWORD=your-db-password
POSTAL_DB_NAME=postal-server-1

# Chatwoot (for conversation notes)
CHATWOOT_API_TOKEN=your-chatwoot-token
CHATWOOT_API_URL=https://chatwoot.fiszu.com

# Notification sender
BOUNCE_SENDER_EMAIL=bounce-bridge@fiszu.com
```

### Configuration File (config.yaml)

Settings can also be edited via the web UI at `/settings`.

## Conversation ID Extraction

Bounce Bridge extracts Chatwoot conversation IDs from:

1. **Email Header**: `X-Chatwoot-Conv-ID: {account_id}:{conv_id}`
2. **HTML Body Comment**: `<!-- cw:{account_id}:{conv_id} -->`

## Companion Services

| Service | Purpose |
|---------|---------|
| [postfix-bounce-monitor](https://github.com/eMobility-Innovations/postfix-bounce-monitor) | Monitors Postfix mail.log, forwards bounces to `/api/v1/postfix-bounce` |
| [mariadb-ssh-proxy](https://github.com/eMobility-Innovations/mariadb-ssh-proxy) | SSH tunnel systemd service for secure MariaDB access |
| [redirect-manager](https://github.com/eMobility-Innovations/redirect-manager) | Manages Postal domain automation, DNS, tracking proxy |
| [postal-grafana-dashboards](https://github.com/eMobility-Innovations/postal-grafana-dashboards) | Grafana dashboards for Postal email analytics |

## Reverse Proxy (Pangolin)

Configure with:
- `/api/*` paths excluded from ForwardAuth (no SSO — webhooks must be unauthenticated)
- All other paths protected by Keycloak ForwardAuth
