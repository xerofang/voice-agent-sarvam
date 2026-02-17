# 🎤 Voice Agent - Simple Deployment

Two-component voice agent for Indian regional languages using Sarvam AI.

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     YOUR COOLIFY VPS                                 │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Component 1: WEB SERVER (main.py)                              ││
│  │  - Coolify deploys this                                         ││
│  │  - Browser test UI on port 3000                                 ││
│  │  - Token generation API                                         ││
│  │  - N8N integration                                              ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Component 2: AGENT WORKER (agent_worker.py)                    ││
│  │  - Run separately via SSH/screen/tmux                           ││
│  │  - Handles actual voice processing                              ││
│  │  - Uses Sarvam AI + LiveKit                                     ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  LIVEKIT CLOUD  │
                    │  (WebRTC relay) │
                    └─────────────────┘
```

## 📁 Files

```
voice-agent-simple/
├── Dockerfile          # For Coolify (web server only)
├── main.py             # Web server + UI
├── agent_worker.py     # Voice agent worker (run separately)
├── requirements.txt    # Python dependencies
└── .env.example        # Environment template
```

## 🚀 Deployment Steps

### Step 1: Deploy Web Server to Coolify

1. Push to GitHub:
   - `Dockerfile`
   - `main.py`
   - `requirements.txt`

2. In Coolify:
   - **Add Resource** → **Application** → **GitHub**
   - Add environment variables (see below)
   - Deploy!

3. Web UI will be available at your Coolify URL

### Step 2: Run Agent Worker

SSH into your VPS and run the agent worker:

```bash
# Install dependencies (if not using Docker)
pip install -r requirements.txt

# Set environment variables
export SARVAM_API_KEY=your_key
export LIVEKIT_API_KEY=your_key
export LIVEKIT_API_SECRET=your_secret
export LIVEKIT_URL=wss://your-project.livekit.cloud
export GROQ_API_KEY=your_key
export WEB_SERVER_URL=http://localhost:3000

# Start the agent worker
python agent_worker.py start
```

Or use screen/tmux to keep it running:
```bash
screen -S voice-agent
python agent_worker.py start
# Press Ctrl+A, D to detach
```

## ⚙️ Environment Variables

### For Coolify (Web Server)

```env
# LiveKit (https://cloud.livekit.io/)
LIVEKIT_API_KEY=your_key
LIVEKIT_API_SECRET=your_secret
LIVEKIT_URL=wss://your-project.livekit.cloud

# N8N (optional)
N8N_BASE_URL=https://your-n8n.com
N8N_WEBHOOK_AGENT_CONFIG=/webhook/agent-config

# Defaults
DEFAULT_LANGUAGE=hi-IN
DEFAULT_VOICE=aditya
```

### For Agent Worker (SSH session)

```env
# All of the above, plus:
SARVAM_API_KEY=your_key
GROQ_API_KEY=your_key
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
WEB_SERVER_URL=http://localhost:3000
```

## 🧪 Testing

1. Open Coolify URL in browser
2. Make sure agent worker is running
3. Click "Start Test Call"
4. Allow microphone
5. Speak in Hindi!

## 🔗 N8N Integration

Import these workflows to N8N:
- `n8n-workflow-agent-profiles.json`
- `n8n-workflow-lead-capture.json`

## 🆘 Troubleshooting

**Web UI shows "Server Online" but calls don't work?**
→ Agent worker is not running. Start it with `python agent_worker.py start`

**"Missing command" error?**
→ You must run the agent with a command: `python agent_worker.py start`

**No audio from agent?**
→ Check SARVAM_API_KEY and GROQ_API_KEY are set in agent worker environment
