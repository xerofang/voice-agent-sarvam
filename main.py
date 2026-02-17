"""
Lead Nurturing Voice Agent - Web Server
========================================
This runs the web UI and API for:
- Browser testing interface
- Token generation for LiveKit
- N8N webhook proxy
- Agent configuration API

For actual voice processing, run the agent_worker.py separately.
"""

import os
import json
from datetime import datetime
from typing import Optional

import httpx
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn

# LiveKit imports
from livekit import api as livekit_api

load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================

class AgentProfile(BaseModel):
    """Agent profile from N8N"""
    id: str = "default"
    name: str = "Lead Nurturing Agent"
    language: str = "hi-IN"
    voice: str = "arya"
    system_prompt: str = ""
    greeting: str = ""
    qualification_questions: list[str] = []
    transfer_keywords: list[str] = []
    fallback_message: str = ""

class ConfigManager:
    """Fetches agent configuration from N8N webhooks"""
    
    def __init__(self):
        self.n8n_base = os.getenv("N8N_BASE_URL", "")
        self.config_endpoint = os.getenv("N8N_WEBHOOK_AGENT_CONFIG", "/webhook/agent-config")
        self.lead_capture_endpoint = os.getenv("N8N_WEBHOOK_LEAD_CAPTURE", "/webhook/lead-capture")
        self._cache: dict[str, AgentProfile] = {}
        self._default = self._create_default()
        
        if self.n8n_base:
            logger.info(f"N8N integration enabled: {self.n8n_base}")
        else:
            logger.info("N8N_BASE_URL not set - using default agent profile")
    
    def _create_default(self) -> AgentProfile:
        return AgentProfile(
            id="default",
            name="Lead Nurturing Agent",
            language=os.getenv("DEFAULT_LANGUAGE", "hi-IN"),
            voice=os.getenv("DEFAULT_VOICE", "arya"),
            system_prompt="""You are a friendly lead nurturing agent for real estate.

Your role:
- Greet callers warmly in Hindi or their preferred language
- Understand their property requirements
- Qualify leads by asking about budget, location, timeline
- Schedule property visits

Guidelines:
- Be warm, professional, and patient
- Use Hinglish (Hindi + English mix) naturally
- Always confirm information before ending

Collect these details:
1. Name
2. Budget range
3. Preferred location/area
4. Property type (apartment/villa/plot)
5. Timeline to buy
6. Best time for site visit""",
            greeting="नमस्ते! RAA Estate में आपका स्वागत है। मैं आपकी कैसे मदद कर सकता हूं?",
            qualification_questions=[
                "आपका बजट क्या है?",
                "आप किस एरिया में प्रॉपर्टी देख रहे हैं?",
                "कब तक खरीदना चाहते हैं?",
            ],
            transfer_keywords=["manager", "human", "complaint"],
            fallback_message="माफ कीजिए, मैं समझ नहीं पाया। क्या आप दोबारा बता सकते हैं?"
        )
    
    async def get_profile(self, agent_id: str = "default") -> AgentProfile:
        if agent_id in self._cache:
            return self._cache[agent_id]
        
        if self.n8n_base:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    url = f"{self.n8n_base}{self.config_endpoint}"
                    response = await client.get(url, params={"agent_id": agent_id})
                    if response.status_code == 200:
                        data = response.json()
                        profile = AgentProfile(**data)
                        self._cache[agent_id] = profile
                        logger.info(f"Loaded profile from N8N: {profile.name}")
                        return profile
            except Exception as e:
                logger.warning(f"N8N fetch failed: {e}, using default")
        
        return self._default
    
    def invalidate(self, agent_id: str = None):
        if agent_id:
            self._cache.pop(agent_id, None)
        else:
            self._cache.clear()

config_manager = ConfigManager()

# ==========================================
# FASTAPI WEB SERVER
# ==========================================

app = FastAPI(title="Voice Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    """Health check endpoint for Coolify/Docker"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/api/token")
async def generate_token(request: Request):
    """Generate LiveKit token for browser testing"""
    try:
        data = await request.json()
        agent_id = data.get("agentId", "default")
        language = data.get("language", "hi-IN")
        voice = data.get("voice", "arya")
        user_name = data.get("userName", f"Tester-{int(datetime.now().timestamp())}")
        
        room_name = f"test-{agent_id}-{int(datetime.now().timestamp())}"
        
        api_key = os.getenv("LIVEKIT_API_KEY")
        api_secret = os.getenv("LIVEKIT_API_SECRET")
        
        if not api_key or not api_secret:
            raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
        
        # Create LiveKit token (new API - grants passed to constructor)
        grant = livekit_api.VideoGrants(
            room=room_name,
            room_join=True,
            can_publish=True,
            can_subscribe=True,
        )

        token = livekit_api.AccessToken(
            api_key=api_key,
            api_secret=api_secret,
        ).with_identity(user_name).with_name(user_name).with_grants(grant)

        jwt_token = token.to_jwt()
        
        return {
            "token": jwt_token,
            "roomName": room_name,
            "livekitUrl": os.getenv("LIVEKIT_URL"),
            "agentId": agent_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/{agent_id}")
async def get_agent_config(agent_id: str = "default"):
    """Get agent configuration (for external agent workers)"""
    profile = await config_manager.get_profile(agent_id)
    return profile.model_dump()

@app.post("/api/invalidate-cache")
async def invalidate_cache(agent_id: str = None):
    """Invalidate cached agent configurations"""
    config_manager.invalidate(agent_id)
    return {"status": "invalidated", "agent_id": agent_id}

@app.get("/api/languages")
async def get_languages():
    """Get available languages and voices"""
    return {
        "languages": [
            {"code": "hi-IN", "name": "Hindi (हिंदी)"},
            {"code": "en-IN", "name": "English (Indian)"},
            {"code": "ta-IN", "name": "Tamil (தமிழ்)"},
            {"code": "te-IN", "name": "Telugu (తెలుగు)"},
            {"code": "bn-IN", "name": "Bengali (বাংলা)"},
            {"code": "mr-IN", "name": "Marathi (मराठी)"},
            {"code": "gu-IN", "name": "Gujarati (ગુજરાતી)"},
            {"code": "kn-IN", "name": "Kannada (ಕನ್ನಡ)"},
            {"code": "ml-IN", "name": "Malayalam (മലയാളം)"},
            {"code": "pa-IN", "name": "Punjabi (ਪੰਜਾਬੀ)"},
            {"code": "or-IN", "name": "Odia (ଓଡ଼ିଆ)"},
            {"code": "unknown", "name": "Auto-detect"},
        ],
        "voices": [
            {"id": "arya", "name": "Arya (Male)"},
            {"id": "abhilash", "name": "Abhilash (Male)"},
            {"id": "karun", "name": "Karun (Male)"},
            {"id": "hitesh", "name": "Hitesh (Male)"},
            {"id": "anushka", "name": "Anushka (Female)"},
            {"id": "manisha", "name": "Manisha (Female)"},
            {"id": "vidya", "name": "Vidya (Female)"},
        ]
    }

# ==========================================
# EMBEDDED WEB UI
# ==========================================

WEB_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voice Agent Console</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/livekit-client@2.0.0/dist/livekit-client.umd.js"></script>
    <style>
        .pulse { animation: pulse 2s infinite; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .visualizer-bar { transition: height 0.1s ease; }
    </style>
</head>
<body class="bg-gray-900 text-white min-h-screen">
    <header class="bg-gray-800 border-b border-gray-700 px-6 py-4">
        <div class="max-w-6xl mx-auto flex items-center justify-between">
            <div class="flex items-center gap-3">
                <span class="text-3xl">🎤</span>
                <div>
                    <h1 class="text-xl font-bold">Voice Agent Console</h1>
                    <p class="text-gray-400 text-sm">Browser-based testing • Sarvam AI</p>
                </div>
            </div>
            <div id="status" class="flex items-center gap-2 text-green-400 text-sm">
                <span class="w-2 h-2 bg-green-400 rounded-full pulse"></span>
                Server Online
            </div>
        </div>
    </header>

    <main class="max-w-6xl mx-auto p-6">
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            <!-- Config Panel -->
            <div class="bg-gray-800 rounded-lg p-6">
                <h2 class="text-xl font-bold mb-6">⚙️ Configuration</h2>
                
                <div class="space-y-4">
                    <div>
                        <label class="block text-gray-300 text-sm mb-2">Agent Profile ID</label>
                        <input type="text" id="agentId" value="default" 
                            class="w-full bg-gray-700 text-white px-4 py-2 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none">
                    </div>
                    
                    <div>
                        <label class="block text-gray-300 text-sm mb-2">Language</label>
                        <select id="language" class="w-full bg-gray-700 text-white px-4 py-2 rounded-lg">
                            <option value="hi-IN">Hindi (हिंदी)</option>
                            <option value="en-IN">English (Indian)</option>
                            <option value="ta-IN">Tamil (தமிழ்)</option>
                            <option value="te-IN">Telugu (తెలుగు)</option>
                            <option value="bn-IN">Bengali (বাংলা)</option>
                            <option value="mr-IN">Marathi (मराठी)</option>
                            <option value="gu-IN">Gujarati (ગુજરાતી)</option>
                            <option value="unknown">Auto-detect</option>
                        </select>
                    </div>
                    
                    <div>
                        <label class="block text-gray-300 text-sm mb-2">Voice</label>
                        <select id="voice" class="w-full bg-gray-700 text-white px-4 py-2 rounded-lg">
                            <option value="arya">Arya (Male)</option>
                            <option value="abhilash">Abhilash (Male)</option>
                            <option value="karun">Karun (Male)</option>
                            <option value="hitesh">Hitesh (Male)</option>
                            <option value="anushka">Anushka (Female)</option>
                            <option value="manisha">Manisha (Female)</option>
                            <option value="vidya">Vidya (Female)</option>
                        </select>
                    </div>
                    
                    <div>
                        <label class="block text-gray-300 text-sm mb-2">Your Name</label>
                        <input type="text" id="userName" value="Tester"
                            class="w-full bg-gray-700 text-white px-4 py-2 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none">
                    </div>
                    
                    <button id="startBtn" onclick="startCall()"
                        class="w-full py-3 rounded-lg font-semibold bg-green-600 hover:bg-green-700 transition-colors">
                        🚀 Start Test Call
                    </button>
                    
                    <button id="stopBtn" onclick="stopCall()" style="display:none"
                        class="w-full py-3 rounded-lg font-semibold bg-red-600 hover:bg-red-700 transition-colors">
                        🔴 End Call
                    </button>
                </div>
                
                <div class="mt-6 p-4 bg-blue-900/30 rounded-lg">
                    <h4 class="text-blue-300 font-medium mb-2">💡 Info</h4>
                    <ul class="text-gray-400 text-sm space-y-1">
                        <li>• Uses browser microphone</li>
                        <li>• Connects to LiveKit Cloud</li>
                        <li>• Agent uses Sarvam AI</li>
                    </ul>
                </div>
            </div>
            
            <!-- Call Interface -->
            <div class="lg:col-span-2 bg-gray-800 rounded-lg p-6">
                <div id="preCall" class="h-full flex flex-col items-center justify-center py-12">
                    <span class="text-6xl mb-4">🎙️</span>
                    <h3 class="text-xl font-semibold mb-2">Ready to Test</h3>
                    <p class="text-gray-400 text-center max-w-md mb-6">
                        Configure settings and click "Start Test Call". 
                        Allow microphone access when prompted.
                    </p>
                    <div class="p-4 bg-yellow-900/30 rounded-lg max-w-md">
                        <p class="text-yellow-300 text-sm text-center">
                            <strong>Note:</strong> Agent worker must be running for voice responses.
                        </p>
                    </div>
                </div>
                
                <div id="inCall" style="display:none" class="h-full flex flex-col">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center gap-3">
                            <div id="statusDot" class="w-3 h-3 rounded-full bg-gray-500"></div>
                            <span id="statusText" class="font-medium">Connecting...</span>
                        </div>
                        <span id="duration" class="text-gray-400">00:00</span>
                    </div>
                    
                    <div class="bg-gray-900 rounded-lg p-6 mb-4">
                        <div id="visualizer" class="flex items-end justify-center gap-1 h-20">
                            <div class="visualizer-bar w-3 bg-green-500 rounded-t" style="height: 20%"></div>
                            <div class="visualizer-bar w-3 bg-green-500 rounded-t" style="height: 40%"></div>
                            <div class="visualizer-bar w-3 bg-green-500 rounded-t" style="height: 60%"></div>
                            <div class="visualizer-bar w-3 bg-green-500 rounded-t" style="height: 80%"></div>
                            <div class="visualizer-bar w-3 bg-green-500 rounded-t" style="height: 60%"></div>
                            <div class="visualizer-bar w-3 bg-green-500 rounded-t" style="height: 40%"></div>
                            <div class="visualizer-bar w-3 bg-green-500 rounded-t" style="height: 20%"></div>
                        </div>
                        <p id="agentStatus" class="text-center text-gray-400 mt-3">Waiting for agent...</p>
                    </div>
                    
                    <div class="flex-1 bg-gray-900 rounded-lg p-4 overflow-y-auto max-h-80">
                        <h4 class="text-white font-semibold mb-3">📝 Transcript</h4>
                        <div id="transcript" class="space-y-3">
                            <p class="text-gray-500 italic">Conversation will appear here...</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <script>
        let room = null;
        let startTime = null;
        let durationInterval = null;

        async function startCall() {
            // Check for secure context (HTTPS required for microphone)
            if (!window.isSecureContext) {
                alert('Microphone access requires HTTPS. Please access this page via HTTPS.');
                return;
            }

            // Check for getUserMedia support
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                alert('Your browser does not support microphone access. Please use a modern browser (Chrome, Firefox, Edge).');
                return;
            }

            const agentId = document.getElementById('agentId').value;
            const language = document.getElementById('language').value;
            const voice = document.getElementById('voice').value;
            const userName = document.getElementById('userName').value;

            document.getElementById('startBtn').disabled = true;
            document.getElementById('startBtn').textContent = '⏳ Connecting...';

            try {
                // Request microphone permission early
                await navigator.mediaDevices.getUserMedia({ audio: true });
                const response = await fetch('/api/token', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ agentId, language, voice, userName })
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Failed to get token');
                }
                const data = await response.json();
                
                room = new LivekitClient.Room({ adaptiveStream: true, dynacast: true });
                
                room.on('connected', () => {
                    updateStatus('connected', 'Connected - waiting for agent...');
                    document.getElementById('agentStatus').textContent = 'Waiting for agent...';
                });
                
                room.on('disconnected', () => stopCall());
                
                room.on('participantConnected', (p) => {
                    if (p.identity.includes('agent')) {
                        updateStatus('speaking', '🤖 Agent Connected');
                        document.getElementById('agentStatus').textContent = 'Agent listening...';
                    }
                });
                
                room.on('trackSubscribed', (track) => {
                    if (track.kind === 'audio') {
                        document.body.appendChild(track.attach());
                        updateStatus('speaking', '🔊 Agent Speaking');
                    }
                });
                
                room.on('activeSpeakersChanged', (speakers) => updateVisualizer(speakers.length > 0));
                
                await room.connect(data.livekitUrl, data.token);
                await room.localParticipant.setMicrophoneEnabled(true);
                
                document.getElementById('preCall').style.display = 'none';
                document.getElementById('inCall').style.display = 'flex';
                document.getElementById('startBtn').style.display = 'none';
                document.getElementById('stopBtn').style.display = 'block';
                
                startTime = Date.now();
                durationInterval = setInterval(updateDuration, 1000);
                updateStatus('listening', '🎤 Listening...');
                
            } catch (error) {
                alert('Failed to start call: ' + error.message);
                document.getElementById('startBtn').disabled = false;
                document.getElementById('startBtn').textContent = '🚀 Start Test Call';
            }
        }
        
        async function stopCall() {
            if (room) { await room.disconnect(); room = null; }
            if (durationInterval) { clearInterval(durationInterval); durationInterval = null; }
            
            document.getElementById('preCall').style.display = 'flex';
            document.getElementById('inCall').style.display = 'none';
            document.getElementById('startBtn').style.display = 'block';
            document.getElementById('stopBtn').style.display = 'none';
            document.getElementById('startBtn').disabled = false;
            document.getElementById('startBtn').textContent = '🚀 Start Test Call';
        }
        
        function updateStatus(state, text) {
            const dot = document.getElementById('statusDot');
            dot.className = 'w-3 h-3 rounded-full ' + 
                (state === 'connected' ? 'bg-yellow-500' : 
                 state === 'listening' ? 'bg-green-500 pulse' : 
                 state === 'speaking' ? 'bg-blue-500 pulse' : 'bg-gray-500');
            document.getElementById('statusText').textContent = text;
        }
        
        function updateDuration() {
            if (!startTime) return;
            const s = Math.floor((Date.now() - startTime) / 1000);
            document.getElementById('duration').textContent = 
                Math.floor(s/60).toString().padStart(2,'0') + ':' + (s%60).toString().padStart(2,'0');
        }
        
        function updateVisualizer(active) {
            document.querySelectorAll('.visualizer-bar').forEach(bar => {
                bar.style.height = active ? (Math.random() * 60 + 20) + '%' : '10%';
            });
        }
        
        setInterval(() => { if (room?.state === 'connected') updateVisualizer(true); }, 150);
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the embedded web UI"""
    return WEB_UI_HTML

# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "3000"))
    logger.info(f"Starting Voice Agent Web Server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
