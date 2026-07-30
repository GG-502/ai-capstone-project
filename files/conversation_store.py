"""
conversation_store.py — Persists conversation state for multi-turn interactions.

Stores conversation history per phone number to support follow-ups.
"""

import json
from pathlib import Path
from datetime import datetime

STORE_FILE = Path(__file__).parent.parent / "data" / "conversation_store.json"


def _ensure_store():
    """Ensure conversation store file exists."""
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_FILE.exists():
        STORE_FILE.write_text("{}")


def get_conversation_history(phone_number: str) -> list[dict]:
    """Get conversation history for a phone number."""
    _ensure_store()
    try:
        with open(STORE_FILE, "r") as f:
            store = json.load(f)
        return store.get(phone_number, {}).get("messages", [])
    except Exception as e:
        print(f"⚠️  Error reading conversation history: {e}")
        return []


def add_message(phone_number: str, role: str, content: str):
    """Add a message to conversation history."""
    _ensure_store()
    try:
        with open(STORE_FILE, "r") as f:
            store = json.load(f)
        
        if phone_number not in store:
            store[phone_number] = {"messages": []}
        
        store[phone_number]["messages"].append({
            "timestamp": datetime.now().isoformat(),
            "role": role,  # "user" or "assistant"
            "content": content
        })
        
        with open(STORE_FILE, "w") as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        print(f"⚠️  Error saving message: {e}")


def clear_conversation(phone_number: str):
    """Clear conversation history for a phone number."""
    _ensure_store()
    try:
        with open(STORE_FILE, "r") as f:
            store = json.load(f)
        
        if phone_number in store:
            del store[phone_number]
        
        with open(STORE_FILE, "w") as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        print(f"⚠️  Error clearing conversation: {e}")
