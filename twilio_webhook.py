"""
twilio_webhook.py — Twilio webhook for SMS integration.

Receives SMS messages from Twilio and runs them through the graph.
Supports multi-turn conversations when initiated with "start".
"""

import os
import sys
import asyncio
import json
from pathlib import Path
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

# Add files folder to path
sys.path.insert(0, str(Path(__file__).parent / "files"))

from app_graph import build_and_run_graph
from state import ConversationState
from tenant_db import normalize_phone_number
from conversation_store import get_conversation_history, add_message

load_dotenv()

app = Flask(__name__)

# Twilio configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_API_KEY")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+15026608679")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

# Store last conversation state for multi-turn support
_conversation_states = {}


@app.route("/sms", methods=["POST"])
def handle_sms():
    """
    Handle incoming SMS from Twilio webhook.
    
    Supports:
    - "start" command to initiate a conversation
    - Multi-turn conversations with state persistence
    - Processes messages through the graph and responds via SMS
    """
    # Get message data
    from_number = request.form.get("From", "").strip()
    message_body = request.form.get("Body", "").strip()
    
    print(f"\n📱 SMS Received: {from_number} → {message_body}")
    
    # Normalize phone number
    phone = normalize_phone_number(from_number)
    
    if not message_body:
        response = MessagingResponse()
        response.message("Please send a message.")
        return str(response)
    
    # Check if "start" command
    if message_body.lower().strip() == "start":
        welcome_message = (
            "Hi! This is Property Assistant. How can I help with your rental property request?"
        )
        
        print(f"📤 Welcome Message: {welcome_message}")
        
        # Send via Twilio
        if client:
            try:
                message = client.messages.create(
                    to=from_number,
                    from_=TWILIO_FROM_NUMBER,
                    body=welcome_message
                )
                print(f"✓ Welcome SMS sent (SID: {message.sid})")
            except Exception as e:
                print(f"✗ SMS send failed: {e}")
        
        # Echo back with Twilio response
        response = MessagingResponse()
        response.message(welcome_message)
        
        # Initialize conversation state
        _conversation_states[phone] = {
            "phone_number": phone,
            "tenant_id": None,
            "tenant_name": None,
            "unit_label": None,
            "address": None,
            "identity_status": "unresolved",
            "message": None,
            "history": [],
            "category": None,
            "resolution_path": None,
            "response": None,
            "_route": None,
        }
        
        return str(response)
    
    # Get previous state if exists
    previous_state = _conversation_states.get(phone)
    
    # Run graph
    try:
        print(f"🔄 Running graph for phone: {phone}")
        
        initial_state: ConversationState = {
            "phone_number": phone,
            "tenant_id": previous_state.get("tenant_id") if previous_state else None,
            "tenant_name": previous_state.get("tenant_name") if previous_state else None,
            "unit_label": previous_state.get("unit_label") if previous_state else None,
            "address": previous_state.get("address") if previous_state else None,
            "identity_status": previous_state.get("identity_status", "unresolved") if previous_state else "unresolved",
            "message": message_body,
            "history": previous_state.get("history", []) if previous_state else [],
            "category": previous_state.get("category") if previous_state else None,
            "resolution_path": previous_state.get("resolution_path") if previous_state else None,
            "response": None,
            "_route": None,
        }
        
        print(f"  Initial state identity_status: {initial_state.get('identity_status')}")
        
        # Run graph (blocking)
        result = asyncio.run(build_and_run_graph(initial_state))
        
        print(f"✓ Graph executed successfully")
        print(f"  Identity status: {result.get('identity_status')}")
        print(f"  Route: {result.get('_route')}")
        
        # Send response via SMS
        response_text = result.get("response", "I'm sorry, I couldn't process your message.")
        
        print(f"📤 SMS Response: {response_text[:100]}...")
        
        # Store updated state for next turn
        _conversation_states[phone] = result
        
        # Send via Twilio
        if client:
            try:
                message = client.messages.create(
                    to=from_number,
                    from_=TWILIO_FROM_NUMBER,
                    body=response_text
                )
                print(f"✓ SMS sent (SID: {message.sid})")
            except Exception as e:
                print(f"✗ SMS send failed: {e}")
        
        # Echo back with Twilio response
        response = MessagingResponse()
        response.message(response_text)
        return str(response)
        
    except Exception as e:
        print(f"✗ Error processing message: {e}")
        
        response = MessagingResponse()
        response.message(f"Sorry, there was an error processing your request. Please try again.")
        return str(response)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print(f"\n🚀 Starting Twilio webhook server on port {port}")
    print(f"   SMS endpoint: http://localhost:{port}/sms")
    app.run(host="0.0.0.0", port=port, debug=True)
