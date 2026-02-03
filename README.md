<div align="center">
  <h1>🚀 nanobot-serverless-deploy</h1>
  <p>One-Click Serverless Deployment for nanobot AI Assistant</p>
  <p>
    Deploy <a href="https://github.com/HKUDS/nanobot">nanobot</a> to popular serverless platforms with zero local setup required.
    Access your AI assistant from Telegram anywhere, anytime.
  </p>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/platform-Google%20Cloud%20Run-orange" alt="Platform">
  </p>
</div>

## ✨ Features

- 🎯 **One-Command Deployment** - Deploy to Google Cloud Run with a single script
- 💰 **Free Tier Support** - Runs entirely on GCP Always-Free tier
- 🔄 **24/7 Availability** - No need to keep your computer running
- 📱 **Telegram Integration** - Full Telegram bot support via webhooks
- 💾 **Persistent Storage** - All data stored in Google Cloud Storage (chat history, sessions, files)
- ⚡ **Serverless Optimized** - Cold start optimization and automatic scaling

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│   Google Cloud Run (Serverless)        │
│  ┌───────────────────────────────────┐  │
│  │  FastAPI HTTP Handler             │  │
│  │  - Telegram webhook endpoint      │  │
│  │  - Health check endpoint          │  │
│  └───────────────────────────────────┘  │
│           │                              │
│           ▼                              │
│  ┌───────────────────────────────────┐  │
│  │  nanobot Gateway Adapter          │  │
│  │  - Initialize from env vars       │  │
│  │  - Handle webhook events          │  │
│  │  - Sync files to/from GCS         │  │
│  └───────────────────────────────────┘  │
│           │                              │
└───────────┼──────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│   External Services                      │
│  - Google Cloud Storage (persistent)    │
│  - OpenRouter API (LLM)                 │
│  - Brave Search API (optional)          │
└─────────────────────────────────────────┘
```

## 🚀 Quick Start

> [!TIP]
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (LLM) · [Brave Search](https://brave.com/search/api/) (optional, for web search)
> You can also change the model to `minimax/minimax-m2` for lower cost.

### Prerequisites

Before deploying, you'll need:

1. **OpenRouter API Key** - Get from [OpenRouter.ai](https://openrouter.ai/keys)
2. **Telegram Bot Token** - Create a bot with [@BotFather](https://t.me/BotFather)
3. **Telegram User ID** - Get from [@userinfobot](https://t.me/userinfobot)
4. **Google Cloud Platform Account** - Create at [cloud.google.com](https://cloud.google.com)

### Deploy to Google Cloud Run

**1. Clone repository**

```bash
git clone elliot35/nanobot-serverless-deploy
cd serverlessbot
```

**2. Configure environment**

```bash
# Copy template
cp .env.example .env

# Edit .env file with your credentials
# Required:
# - NANOBOT_OPENROUTER_API_KEY
# - TELEGRAM_BOT_TOKEN
# - TELEGRAM_ALLOWED_USERS
# Optional:
# - GCS_BUCKET_NAME (auto-created if not set)
# - NANOBOT_MODEL (defaults to anthropic/claude-opus-4-5)
# - BRAVE_SEARCH_API_KEY
```

**3. Set GCP project**

```bash
export GCP_PROJECT_ID=your-project-id
# Or set it permanently:
gcloud config set project your-project-id
```

**4. Load environment variables**

```bash
# For bash/zsh:
set -a
source .env
set +a
```

**5. Deploy**

```bash
./gcp/deploy.sh
```

The script will:
- ✅ Enable required GCP APIs
- ✅ Create GCS bucket for persistent storage
- ✅ Build and push Docker image
- ✅ Deploy to Cloud Run
- ✅ Provide service URL and next steps

**6. Set Telegram webhook**

After deployment, the script will output your service URL. Then:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook?url=https://your-service-url.run.app/api/webhook/telegram"
```

**7. Test**

Send a message to your bot on Telegram - it should respond!

## 💾 Storage

All data is automatically stored in **Google Cloud Storage**:

| Data Type | Storage Location | Format |
|-----------|----------------|--------|
| **Chat History** | `sessions/{session_key}/chat_history.jsonl` | JSONL (one message per line) |
| **Sessions** | `sessions/{session_key}/session.json` | JSON |
| **Agent Actions** | `sessions/{session_key}/agent_actions.jsonl` | JSONL |
| **Files** | `sessions/{session_key}/files/` | Any file type |

**Automatic syncing:**
- Files are synced **from** GCS before processing (agent can access previous files)
- Chat history is loaded automatically (up to 50 previous messages)
- Files are synced **to** GCS after processing (persists across invocations)

## 📋 Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `NANOBOT_OPENROUTER_API_KEY` | OpenRouter API key for LLM access | `sk-or-v1-xxx` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | `123456:ABC...` |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated list of allowed user IDs | `123456789,987654321` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `GCS_BUCKET_NAME` | GCS bucket name for storage | `{PROJECT_ID}-nanobot-files` |
| `GCP_PROJECT_ID` | GCP project ID | Auto-detected from gcloud |
| `NANOBOT_MODEL` | LLM model identifier | `anthropic/claude-opus-4-5` |
| `BRAVE_SEARCH_API_KEY` | Brave Search API key | - |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |

See [`.env.example`](.env.example) for a complete example.

## 🧪 Testing

### Health Check

```bash
curl https://your-service-url.run.app/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "checks": {
    "bus": true,
    "agent_loop": true,
    "session_manager": true,
    "config": true,
    "workspace": true,
    "storage_manager": true,
    "gcs": true
  }
}
```

### View Logs

```bash
gcloud run services logs read nanobot-gateway \
  --region us-central1 \
  --project your-project-id \
  --limit 50
```

## 🗑️ Cleanup

To remove all deployed resources:

```bash
export GCP_PROJECT_ID=your-project-id
./gcp/destroy.sh
```

This will delete:
- ✅ Telegram webhook
- ✅ Cloud Run service
- ✅ Container images
- ⚠️ GCS bucket (optional, with confirmation)

**Note:** GCS data (sessions, chat history, files) will be preserved unless you choose to delete the bucket.

## 💰 Free Tier Limits

### Google Cloud Run (Always-Free)
- ✅ 2 million requests/month
- ✅ 360,000 GB-seconds compute/month
- ✅ 180,000 vCPU-seconds/month
- ✅ 1 GB egress/month
- ⚠️ Requires billing account (but stays within free tier for small usage)

### Google Cloud Storage (Always-Free)
- ✅ 5GB storage/month
- ✅ 1GB egress/month
- ✅ Automatic scaling
- ⚠️ Requires billing account (but stays within free tier for small usage)

## 🐛 Troubleshooting

<details>
<summary><b>Health check returns "unhealthy"</b></summary>

1. **Check logs** for detailed error messages:
   ```bash
   gcloud run services logs read nanobot-gateway --region us-central1 --project your-project-id --limit 50
   ```

2. **Common issues:**
   - Missing environment variables (especially `GCS_BUCKET_NAME`)
   - Invalid API keys or tokens
   - GCS bucket permissions issues
   - Import errors (check that nanobot is installed correctly)

</details>

<details>
<summary><b>Bot not responding</b></summary>

1. **Check webhook is set correctly:**
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
   ```

2. **Verify webhook URL** matches your deployment URL exactly

3. **Check logs** for errors:
   ```bash
   gcloud run services logs read nanobot-gateway --region us-central1
   ```

4. **Verify environment variables** are set correctly in Cloud Run

5. **Check user ID** is in `TELEGRAM_ALLOWED_USERS` (comma-separated, no spaces)

</details>

<details>
<summary><b>GCS storage errors</b></summary>

1. **Verify bucket exists:**
   ```bash
   gsutil ls gs://your-bucket-name
   ```

2. **Check bucket permissions** - Cloud Run service account needs `storage.objectAdmin` role:
   ```bash
   gsutil iam ch serviceAccount:PROJECT_ID@appspot.gserviceaccount.com:roles/storage.objectAdmin gs://your-bucket-name
   ```

3. **Verify GCS_BUCKET_NAME** environment variable is set correctly

4. **Check GCS API is enabled:**
   ```bash
   gcloud services enable storage-api.googleapis.com --project your-project-id
   ```

</details>

<details>
<summary><b>Cold start delays</b></summary>

- First request may take 5-10 seconds (cold start)
- Subsequent requests are faster (warm instances)
- Consider increasing min instances for production:
  ```bash
  gcloud run services update nanobot-gateway \
    --min-instances 1 \
    --region us-central1
  ```

</details>

## 📁 Project Structure

```
serverlessbot/
├── README.md                    # This file
├── .env.example                 # Environment variables template
├── gcp/
│   ├── main.py                 # Cloud Run FastAPI app
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # Docker image for Cloud Run
│   ├── cloudbuild.yaml         # Cloud Build configuration
│   ├── deploy.sh               # One-command deployment script
│   └── destroy.sh              # Cleanup script
├── src/
│   ├── adapter.py              # nanobot gateway adapter
│   ├── config.py               # Environment-based config loader
│   ├── storage.py              # GCS persistent storage
│   └── handlers.py             # HTTP request handlers
└── scripts/
    └── setup_mongodb.py        # (Deprecated - no longer needed)
```

## 🔧 Local Development

```bash
# Clone repository
git clone <YOUR_REPO_URL>
cd serverlessbot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r gcp/requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env file with your credentials

# Load environment variables
set -a
source .env
set +a

# Run locally
python -m uvicorn gcp.main:app --host 0.0.0.0 --port 8080

# Test health endpoint
curl http://localhost:8080/api/health
```

## 📚 Additional Resources

- [nanobot Documentation](https://github.com/HKUDS/nanobot)
- [Google Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Google Cloud Storage Documentation](https://cloud.google.com/storage/docs)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [OpenRouter Documentation](https://openrouter.ai/docs)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built for [nanobot](https://github.com/HKUDS/nanobot) by HKUDS
- Inspired by the need for easy serverless deployment

---

<div align="center">
  <p>Made with ❤️ for the nanobot community</p>
  <p>
    <a href="#-quick-start">Get Started</a> •
    <a href="#-troubleshooting">Troubleshooting</a> •
    <a href="#-cleanup">Cleanup</a>
  </p>
</div>
