"""
app.py — CLI interface for Property Assistant

Simplified to use the core graph logic from app_graph.py
Can be run in CLI mode or integrated with Twilio webhook (twilio_webhook.py)

Usage:
    CLI: python3 app.py
    Webhook: python3 twilio_webhook.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import asyncio
from twilio.rest import Client

# Add files folder to path
sys.path.insert(0, str(Path(__file__).parent / "files"))

from app_graph import build_and_run_graph
from state import ConversationState  # type: ignore
import google_calendar  # type: ignore

load_dotenv()


def format_phone_number(phone: str) -> str:
    """Format phone number to E.164 format for Twilio."""
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    # If 10 digits, assume US (502 area code)
    if len(digits) == 10:
        return f"+1{digits}"
    # If already 11+ digits with leading 1, add +
    elif len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    # Otherwise, assume it's already formatted or needs manual fix
    elif not digits.startswith('1'):
        return f"+1{digits}"
    return f"+{digits}"


def send_sms_response(phone_number: str, response_text: str) -> bool:
    """
    Send response via SMS using Twilio.
    
    Args:
        phone_number: Recipient phone number (will be formatted to E.164)
        response_text: Message to send
        
    Returns:
        True if successful, False otherwise
    """
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_API_KEY")
        from_number = os.getenv("TWILIO_FROM_NUMBER")
        
        if not all([account_sid, auth_token, from_number]):
            print("❌ Twilio credentials missing in .env file")
            return False
        
        # Format phone number to E.164
        formatted_phone = format_phone_number(phone_number)
        
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            to=formatted_phone,
            from_=from_number,
            body=response_text
        )
        
        print(f"✓ SMS sent successfully (SID: {message.sid})")
        return True
    except Exception as e:
        print(f"⚠ SMS sending failed: {e}")
        return False


async def main():
    """Run the TEXT AGENT workflow via CLI."""
    try:
        # Run the workflow
        print("\n" + "="*50)
        print("TEXT AGENT - Property Assistant")
        print("Architecture: property_assistant_architecture.md")
        print("Mode: CLI (for Twilio webhook, run: python3 twilio_webhook.py)")
        print("="*50 + "\n")
        
        # Get initial input
        phone_number = input("Enter phone number: ").strip()
        if not phone_number:
            phone_number = os.getenv("MANAGER_PHONE_NUMBER", "555-0001")
        
        message = input("Enter message: ").strip()
        if not message:
            print("Message cannot be empty")
            return
        
        # Initialize state per architecture Section 3a
        initial_state: ConversationState = {
            "phone_number": phone_number,
            "tenant_id": None,
            "tenant_name": None,
            "unit_label": None,
            "address": None,
            "identity_status": "unresolved",
            "message": message,
            "history": [],
            "category": None,
            "resolution_path": None,
            "response": None,
            "_route": None,
        }
        
        # Run the graph
        result = await build_and_run_graph(initial_state)
        
        # Send response via SMS
        if result['response']:
            print("\nSending response via SMS...")
            send_sms_response(phone_number, result['response'])
        
        print("\n" + "="*50)
        print("WORKFLOW COMPLETE")
        print("="*50 + "\n")
        print("FINAL RESPONSE:")
        print(result['response'] if result['response'] else "(No response generated)")
        print("\nState Summary:")
        print(f"  Identity Status: {result['identity_status']}")
        print(f"  Category: {result['category']}")
        print(f"  Resolution Path: {result['resolution_path']}")
        
        # Show calendar events
        try:
            events = google_calendar.get_all_events()
            if events:
                print(f"\n📅 Calendar Events (Google Calendar):")
                for event in events[:5]:  # Show first 5 upcoming events
                    title = event.get('summary', 'Untitled')
                    start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', 'N/A'))
                    print(f"  - {title}")
                    print(f"    {start}")
            else:
                print("\n📅 No upcoming events")
        except Exception as e:
            print(f"\n⚠️  Could not retrieve calendar events: {e}")
        
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print("\n📍 To fix this issue:")
        print("  1. Make sure you are in the capstone-project directory")
        print("  2. Ensure the files folder exists with state.py and nodes.py")
        print(f"\n📁 Current working directory: {os.getcwd()}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n🔍 Debug information:")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
