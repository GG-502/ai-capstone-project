"""
nodes.py — resolve_identity node (Section 3b, Text Agent).

Two branches:
  CONFIRM — phone number matched exactly one tenant. Ask a yes/no.
  ASK     — no match (or the tenant said "no" to a confirm). Ask open-ended
            for name or unit number, then try a loose match.

PENDING_STORE now persists to disk so identity confirmation survives across
multiple app runs (e.g., when integrated with Twilio webhook).
"""

import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "data"))
import tenant_db  # noqa: E402

from state import ConversationState  # noqa: E402

# File-based persistence for identity confirmation state
PENDING_STORE_FILE = Path(__file__).parent.parent / "data" / "pending_store.json"

# Ensure data directory exists
PENDING_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_pending_store() -> dict:
    """Load pending store from disk."""
    if PENDING_STORE_FILE.exists():
        try:
            with open(PENDING_STORE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  Could not load pending store: {e}")
            return {}
    return {}


def _save_pending_store(store: dict) -> None:
    """Save pending store to disk."""
    try:
        with open(PENDING_STORE_FILE, "w") as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save pending store: {e}")


# Load pending store on startup
PENDING_STORE: dict[str, dict] = _load_pending_store()


def resolve_identity(state: ConversationState) -> ConversationState:
    phone = state["phone_number"]
    
    # If identity is already confirmed, don't re-verify
    if state.get("identity_status") == "confirmed":
        return state
    
    pending = PENDING_STORE.get(phone)

    if pending:
        return _handle_pending_reply(state, pending)

    tenant = tenant_db.get_tenant_by_phone(phone)

    if tenant:
        # CONFIRM branch — exact single match
        # Save original message so we can reprocess it after identity confirmation
        PENDING_STORE[phone] = {
            "mode": "confirm",
            "candidate": tenant,
            "original_message": state["message"]
        }
        _save_pending_store(PENDING_STORE)
        state["identity_status"] = "pending_confirmation"
        first_name = tenant["name"].split()[0]
        unit_str = f", {tenant['unit_label']}" if tenant["unit_label"] else ""
        state["response"] = (
            f"Hi, thanks for reaching out! Before we start troubleshooting, "
            f"I need to confirm I know who I'm talking to. Is this {first_name} "
            f"at {tenant['address']}{unit_str}? Just enter 1 for yes and 2 for no."
        )
        return state

    # ASK branch — no phone match at all
    PENDING_STORE[phone] = {
        "mode": "ask",
        "original_message": state["message"]
    }
    _save_pending_store(PENDING_STORE)
    state["identity_status"] = "pending_confirmation"
    state["response"] = (
        "Hi! I don't recognize this number yet — "
        "can you tell me your name or unit number?"
    )
    return state


def _handle_pending_reply(state: ConversationState, pending: dict) -> ConversationState:
    phone = state["phone_number"]
    reply = state["message"].strip()

    if pending["mode"] == "confirm":
        candidate = pending["candidate"]

        if reply == "1":
            _set_confirmed(state, candidate)
            # Don't delete yet - keep for maintenance_option mode
            return state

        if reply == "2":
            # wrong person on file for this number — fall back to ASK
            PENDING_STORE[phone] = {"mode": "ask"}
            _save_pending_store(PENDING_STORE)
            state["identity_status"] = "pending_confirmation"
            state["response"] = "Sorry about that! Can you tell me your name or unit number?"
            return state

        state["response"] = "Sorry, I didn't catch that — please reply 1 for yes or 2 for no."
        return state

    if pending["mode"] == "maintenance_option":
        # Identity already confirmed, just waiting for maintenance option selection
        # Only set confirmed if this is a valid maintenance option response
        if reply in ["1", "2"]:
            state["identity_status"] = "confirmed"
            # DON'T restore original message - keep the "1" or "2" response
            return state
        else:
            # Invalid response to maintenance option - just clear this flag and continue processing
            # The identity is already confirmed, just treat this as a regular maintenance message
            del PENDING_STORE[phone]
            _save_pending_store(PENDING_STORE)
            # Keep identity as confirmed - don't restart verification
            state["identity_status"] = "confirmed"
            # Continue processing with the current message
            return state

    if pending["mode"] == "ask":
        matches = tenant_db.find_tenants_by_name_or_unit(reply)

        if len(matches) == 1:
            _set_confirmed(state, matches[0])
            del PENDING_STORE[phone]
            _save_pending_store(PENDING_STORE)
            return state

        if len(matches) > 1:
            state["identity_status"] = "pending_confirmation"
            state["response"] = (
                "I found a few matches — can you give me your full name and unit number?"
            )
            return state

        state["identity_status"] = "pending_confirmation"
        state["response"] = "I couldn't find that — could you double check your name or unit number?"
        return state

    raise ValueError(f"Unknown pending mode: {pending['mode']}")


def _set_confirmed(state: ConversationState, tenant: dict) -> None:
    state["tenant_id"] = tenant["tenant_id"]
    state["tenant_name"] = tenant["name"]
    state["unit_label"] = tenant["unit_label"]
    state["address"] = tenant["address"]
    state["identity_status"] = "confirmed"
    
    # Update pending store to track that we're now awaiting maintenance option selection
    phone = state["phone_number"]
    if phone in PENDING_STORE:
        pending = PENDING_STORE[phone]
        # Change mode to indicate identity is confirmed and we're awaiting maintenance option
        pending["mode"] = "maintenance_option"  # Changed from "confirm"
        pending["context"] = "awaiting_maintenance_option"
        _save_pending_store(PENDING_STORE)
    
    # Retrieve original message from pending store if available
    if phone in PENDING_STORE:
        pending = PENDING_STORE[phone]
        if "original_message" in pending:
            # Restore original message so it gets reprocessed through emergency/categorize nodes
            state["message"] = pending["original_message"]
    
    # response left as None on purpose — in the full graph, categorize()
    # runs next and sets the actual reply. A confirmed identity by itself
    # doesn't produce tenant-facing text.
    state["response"] = None
