"""
twilio_client.py — Twilio SMS client wrapper.

Provides simplified interface for sending SMS messages via Twilio.
"""

import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_API_KEY")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+15026608679")

# Initialize client (if credentials available)
_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    _client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_sms(to_number: str, message_body: str) -> dict:
    """
    Send SMS via Twilio.
    
    Args:
        to_number: Recipient phone number
        message_body: Message text
    
    Returns:
        Dict with message_sid (success) or error
    """
    if not _client:
        print(f"⚠️  Twilio not configured (to: {to_number})")
        return {"error": "Twilio credentials not configured"}
    
    try:
        message = _client.messages.create(
            to=to_number,
            from_=TWILIO_FROM_NUMBER,
            body=message_body
        )
        print(f"✓ SMS sent: {to_number} (SID: {message.sid})")
        return {"message_sid": message.sid, "status": "queued"}
    except Exception as e:
        print(f"✗ SMS send failed: {e}")
        return {"error": str(e)}


def send_sms_to_phone_list(phone_numbers: list, message_body: str) -> dict:
    """
    Send SMS to multiple phone numbers.
    
    Args:
        phone_numbers: List of recipient phone numbers
        message_body: Message text
    
    Returns:
        Dict with success/failure counts and message SIDs
    """
    results = {
        "total": len(phone_numbers),
        "success": 0,
        "failed": 0,
        "message_sids": [],
        "errors": []
    }
    
    for phone in phone_numbers:
        result = send_sms(phone, message_body)
        if "message_sid" in result:
            results["success"] += 1
            results["message_sids"].append(result["message_sid"])
        else:
            results["failed"] += 1
            results["errors"].append(f"{phone}: {result.get('error', 'Unknown error')}")
    
    return results
