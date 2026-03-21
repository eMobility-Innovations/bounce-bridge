# Chatwoot Integration

Bounce Bridge can post private notes to Chatwoot conversations when an email bounce is detected. This allows support agents to see bounce notifications directly in the conversation thread.

## How It Works

When a bounce is processed, Bounce Bridge attempts to extract a Chatwoot conversation ID from the original email. If found, it posts a private note to that conversation with bounce details.

## Tagging Emails with Conversation IDs

For Bounce Bridge to link bounces back to Chatwoot conversations, you must include the conversation ID in outgoing emails. There are two supported methods:

### Method 1: Email Header (Recommended)

Add a custom header to your outgoing emails:

```
X-Chatwoot-Conv-ID: {account_id}:{conversation_id}
```

**Example:**
```
X-Chatwoot-Conv-ID: 1:12345
```

This indicates:
- Account ID: `1`
- Conversation ID: `12345`

### Method 2: HTML Body Comment

Embed a comment in the HTML body of your email:

```html
<!-- cw:{account_id}:{conversation_id} -->
```

**Example:**
```html
<!DOCTYPE html>
<html>
<head>...</head>
<body>
  <!-- cw:1:12345 -->
  <p>Hello, thank you for contacting us...</p>
</body>
</html>
```

## Format Specification

| Field | Format | Description |
|-------|--------|-------------|
| `account_id` | Integer | Your Chatwoot account ID (visible in the URL when logged in) |
| `conversation_id` | Integer | The conversation ID from Chatwoot |

**Combined format:** `{account_id}:{conversation_id}`

- Both IDs must be numeric
- Separated by a single colon (`:`)
- No spaces around the colon
- Header is case-insensitive (`X-Chatwoot-Conv-ID` or `x-chatwoot-conv-id`)

## Priority

If both header and body comment are present, the **header takes priority**.

## Finding Your IDs

### Account ID
Your account ID is visible in the Chatwoot URL:
```
https://chatwoot.example.com/app/accounts/{account_id}/dashboard
```

### Conversation ID
The conversation ID appears in the conversation URL:
```
https://chatwoot.example.com/app/accounts/1/conversations/{conversation_id}
```

## Implementation in Your Email System

### Postal (via SMTP API)
```json
{
  "to": ["customer@example.com"],
  "from": "support@example.com",
  "subject": "Re: Your inquiry",
  "html_body": "<p>Thank you for your email...</p>",
  "headers": {
    "X-Chatwoot-Conv-ID": "1:12345"
  }
}
```

### Ruby/Rails
```ruby
mail = Mail.new do
  to 'customer@example.com'
  from 'support@example.com'
  subject 'Re: Your inquiry'
  headers['X-Chatwoot-Conv-ID'] = "#{account_id}:#{conversation_id}"
  body 'Thank you for your email...'
end
```

### Python
```python
import smtplib
from email.mime.text import MIMEText

msg = MIMEText('Thank you for your email...')
msg['Subject'] = 'Re: Your inquiry'
msg['From'] = 'support@example.com'
msg['To'] = 'customer@example.com'
msg['X-Chatwoot-Conv-ID'] = f'{account_id}:{conversation_id}'
```

### Node.js (Nodemailer)
```javascript
const transporter = nodemailer.createTransport({...});

await transporter.sendMail({
  from: 'support@example.com',
  to: 'customer@example.com',
  subject: 'Re: Your inquiry',
  html: '<p>Thank you for your email...</p>',
  headers: {
    'X-Chatwoot-Conv-ID': `${accountId}:${conversationId}`
  }
});
```

## Bounce Note Format

When a bounce is linked to a conversation, Bounce Bridge posts a private note like:

```
Email bounce detected

Recipient: customer@example.com
Type: HardBounce
Reason: 550 5.1.1 The email account does not exist
Source: AWS SES

The recipient has been added to the suppression list.
```

## Troubleshooting

### Bounce not appearing in conversation
1. Verify the header/comment is present in the original email
2. Check that account_id and conversation_id are valid integers
3. Ensure Chatwoot API token is configured in Bounce Bridge settings
4. Check Bounce Bridge logs for API errors

### Finding bounces without conversation IDs
Check the Bounce Bridge dashboard - bounces without conversation IDs will show "-" in the Chatwoot column.
