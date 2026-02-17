"""
Voice Agent Worker
==================
This is the LiveKit agent worker that handles actual voice calls.
Run this separately from the web server.

Usage:
    python agent_worker.py start
    python agent_worker.py dev  # For development with auto-reload
"""

import os
import json
import asyncio
from datetime import datetime

import httpx
from dotenv import load_dotenv
from loguru import logger

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    AutoSubscribe,
)
from livekit.plugins import sarvam, openai as lk_openai

load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================

WEB_SERVER_URL = os.getenv("WEB_SERVER_URL", "http://localhost:3000")

async def get_agent_config(agent_id: str = "default") -> dict:
    """Fetch agent configuration from web server"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{WEB_SERVER_URL}/api/config/{agent_id}"
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning(f"Failed to fetch config from web server: {e}")
    
    # Default configuration
    return {
        "id": "default",
        "name": "Lead Nurturing Agent",
        "language": os.getenv("DEFAULT_LANGUAGE", "hi-IN"),
        "voice": os.getenv("DEFAULT_VOICE", "arya"),
        "system_prompt": """You are a friendly lead nurturing agent for real estate.

Your role:
- Greet callers warmly in Hindi or their preferred language
- Understand their property requirements
- Qualify leads by asking about budget, location, timeline
- Schedule property visits

Guidelines:
- Be warm, professional, and patient
- Use Hinglish (Hindi + English mix) naturally
- Always confirm information before ending""",
        "greeting": "नमस्ते! RAA Estate में आपका स्वागत है। मैं आपकी कैसे मदद कर सकता हूं?",
        "fallback_message": "माफ कीजिए, मैं समझ नहीं पाया। क्या आप दोबारा बता सकते हैं?"
    }

# ==========================================
# VOICE AGENT
# ==========================================

class LeadNurtureAgent(Agent):
    def __init__(self, config: dict):
        self.config = config
        self.transcript = []
        self.start_time = datetime.now()
        super().__init__(instructions=config.get("system_prompt", ""))
    
    async def on_enter(self):
        """Called when agent enters the room"""
        greeting = self.config.get("greeting")
        if greeting:
            self.session.say(greeting)

async def agent_entrypoint(ctx: JobContext):
    """Main entrypoint for the LiveKit agent"""
    logger.info(f"Agent job started: {ctx.job.id}")
    
    # Get agent ID from room metadata or room name
    agent_id = "default"
    if ctx.room.metadata:
        try:
            metadata = json.loads(ctx.room.metadata)
            agent_id = metadata.get("agent_id", "default")
        except:
            pass
    
    # Try to extract agent_id from room name (format: test-{agent_id}-{timestamp})
    room_name = ctx.room.name
    if room_name.startswith("test-"):
        parts = room_name.split("-")
        if len(parts) >= 2:
            agent_id = parts[1]
    
    logger.info(f"Using agent profile: {agent_id}")
    
    # Fetch configuration
    config = await get_agent_config(agent_id)
    
    # Connect to the room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    # Configure Sarvam AI for STT
    language = config.get("language", "hi-IN")
    stt = sarvam.STT(
        language=language if language != "unknown" else "unknown",
        model="saaras:v3",
    )
    
    # Configure Sarvam AI for TTS
    # bulbul:v2 compatible speakers: anushka, manisha, vidya, arya, abhilash, karun, hitesh
    tts = sarvam.TTS(
        model="bulbul:v2",
        speaker=config.get("voice", "arya"),
        target_language_code=language if language != "unknown" else "hi-IN",
    )
    
    # Configure LLM
    llm_provider = os.getenv("LLM_PROVIDER", "groq")
    if llm_provider == "groq":
        llm = lk_openai.LLM(
            model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY")
        )
    else:
        llm = lk_openai.LLM(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY")
        )
    
    # Create agent session
    session = AgentSession(
        stt=stt,
        tts=tts,
        llm=llm,
        turn_detection="stt",
        min_endpointing_delay=0.07
    )
    
    # Start the agent
    agent = LeadNurtureAgent(config)
    session.start(ctx.room, agent)
    
    logger.info(f"Agent started: {config.get('name')}, Language: {language}, Voice: {config.get('voice')}")

# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Voice Agent Worker")
    logger.info("=" * 50)
    logger.info(f"Web Server URL: {WEB_SERVER_URL}")
    logger.info(f"LLM Provider: {os.getenv('LLM_PROVIDER', 'groq')}")
    logger.info("")
    logger.info("Starting LiveKit agent worker...")
    logger.info("Run with: python agent_worker.py start")
    logger.info("=" * 50)
    
    cli.run_app(WorkerOptions(entrypoint_fnc=agent_entrypoint))
