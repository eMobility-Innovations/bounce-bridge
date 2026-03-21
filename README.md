# Bounce Bridge

Email bounce notification bridge for AWS SES, Postal, and Postfix.

## Overview

Bounce Bridge receives bounce and complaint notifications from multiple sources and:
1. Adds recipients to Postal suppression list with appropriate expiry
2. Sends bounce notification emails to original senders
3. Posts private notes to Chatwoot conversations (if conversation ID found)

## Sources

| Source | Webhook Endpoint |
|--------|------------------|
| AWS SES (via n8n) | `POST /api/v1/ses-bounce` |
| Postal | `POST /api/v1/postal-bounce` |
| Postfix | `POST /api/v1/postfix-bounce` |

## Suppression Expiry

| Source | Type | Expiry |
|--------|------|--------|
| AWS SES | Permanent Bounce | 365 days |
| AWS SES | Transient Bounce | 30 days |
| AWS SES | Complaint | 180 days |
| Postal | Any Bounce | 30 days |
| Postfix | Hard (5.x.x) | 365 days |
| Postfix | Soft (4.x.x) | 30 days |

## Installation

### On CT176

```bash
# Install dependencies
apt update && apt install -y python3 python3-pip python3-venv git sqlite3

# Clone repository
git clone https://github.com/eMobility-Innovations/bounce-bridge.git /opt/bounce-bridge
cd /opt/bounce-bridge

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your credentials

# Create data directory
mkdir -p data

# Install systemd service
cp bounce-bridge.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bounce-bridge
systemctl start bounce-bridge
```

### Postfix Hook (on CT200)

```bash
# Copy the hook script
cp /opt/bounce-bridge/postfix/postfix-bounce-hook.py /opt/
chmod +x /opt/postfix-bounce-hook.py

# Add to crontab to run every minute
echo "* * * * * root /opt/postfix-bounce-hook.py >> /var/log/postfix-bounce-hook.log 2>&1" > /etc/cron.d/postfix-bounce-hook

# Or run in watch mode as a service (see postfix-bounce-hook.service)
```

## Configuration

### Environment Variables (.env)

```
POSTAL_API_KEY=your-postal-api-key
POSTAL_API_URL=https://postal.voltnation.pl
CHATWOOT_API_TOKEN=your-chatwoot-token
CHATWOOT_API_URL=https://chatwoot.fiszu.com
BOUNCE_SENDER_EMAIL=bounce-bridge@fiszu.com
```

### Configuration File (config.yaml)

Settings can also be edited via the web UI at `/settings`.

## Conversation ID Extraction

Bounce Bridge extracts Chatwoot conversation IDs from:

1. **Email Header**: `X-Chatwoot-Conv-ID: {account_id}:{conv_id}`
2. **HTML Body Comment**: `<!-- cw:{account_id}:{conv_id} -->`

The format includes `account_id` so one Bounce Bridge instance can serve multiple Chatwoot accounts.

## API Endpoints

### Webhooks (no auth)

- `POST /api/v1/ses-bounce` - Receive SES SNS notifications
- `POST /api/v1/postal-bounce` - Receive Postal webhooks
- `POST /api/v1/postfix-bounce` - Receive Postfix DSN notifications
- `GET /api/v1/health` - Health check

### UI (SSO protected)

- `GET /` - Dashboard with recent bounces
- `GET /settings` - Configuration page

## Reverse Proxy (Pangolin)

Configure reverse proxy with:
- `/api/*` paths excluded from ForwardAuth (no SSO)
- All other paths protected by Keycloak ForwardAuth

## License

MIT
