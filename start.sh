#!/bin/bash

# Start Web UI + API in background
python main.py &

# Start Voice Agent Worker (foreground to keep container alive)
python agent_worker.py start
