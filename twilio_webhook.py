"""
twilio_webhook.py — Twilio webhook for SMS integration.

Receives SMS messages from Twilio and runs them through the graph.
"""

import os
import sys
import asyncio
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

load_dotenv()

app = Flask(__name__)

# Twilio configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_API_KEY")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+15026608679")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None


@app.route("/sms", methods=["POST"])
def handle_sms():
    """
    Handle incoming SMS from Twilio webhook.
    
    Processes the message through the graph and responds via SMS.
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
    
    # Run graph
    try:
        initial_state: ConversationState = {
            "phone_number": phone,
            "tenant_id": None,
            "tenant_name": None,
            "unit_label": None,
            "address": None,
            "identity_status": "unresolved",
            "message": message_body,
            "history": [],
            "category": None,
            "resolution_path": None,
            "response": None,
            "_route": None,
        }
        
        # Run graph (blocking)
        result = asyncio.run(build_and_run_graph(initial_state))
        
        # Send response via SMS
        response_text = result.get("response", "I'm sorry, I couldn't process your message.")
        
        print(f"📤 SMS Response: {response_text[:100]}...")
        
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
