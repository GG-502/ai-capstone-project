"""
google_calendar.py — Google Calendar API integration.

Handles appointment scheduling, availability checking, and event creation.
Includes get_next_available_slot() with 2-hour travel buffer.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

# Load environment variables
load_dotenv()

# Calendar configuration
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDS_FILE = Path(__file__).parent.parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent.parent / "token.json"
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")  # Property Assistant calendar

# Scheduling constraints
ALLOWED_DAYS = ["Monday", "Tuesday", "Thursday"]  # Not Wed/Fri
ALLOWED_HOURS = (9, 20)  # 9am-8pm
BUFFER_HOURS = 2  # Minimum 2 hours from now for appointments


def _get_credentials():
    """Get Google Calendar API credentials."""
    if not GOOGLE_AVAILABLE:
        return None
    
    creds = None
    
    # Load existing token
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    
    # If no valid credentials, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if CREDS_FILE.exists():
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)
            else:
                print("⚠️  credentials.json not found")
                return None
        
        # Save token for next run
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    
    return creds


def _is_time_allowed(dt: datetime) -> bool:
    """
    Check if a datetime is within allowed scheduling window.
    
    Constraints:
    - 9am-8pm (20:00)
    - Monday, Tuesday, Thursday only (not Wed/Fri)
    """
    day_name = dt.strftime("%A")
    hour = dt.hour
    
    # Check day (not Wed/Fri)
    if day_name not in ALLOWED_DAYS:
        return False
    
    # Check hours (9am-8pm = 9-20)
    if hour < ALLOWED_HOURS[0] or hour >= ALLOWED_HOURS[1]:
        return False
    
    return True


def get_next_available_slot(
    start_date: Optional[datetime] = None,
    hours_to_check: int = 24 * 7
) -> Optional[dict]:
    """
    Get next available appointment slot with 2-hour travel buffer.
    
    Logic:
    1. Start from NOW + 2 hours (travel/prep time)
    2. Round UP to next full hour boundary
    3. Check if slot is within allowed times (Mon/Tue/Thu 9am-8pm)
    4. Return first available or None
    
    Args:
        start_date: Start searching from this time (default: now)
        hours_to_check: How many hours to search ahead (default: 7 days)
    
    Returns:
        Dict with keys: start_time (ISO), end_time (ISO), day_name, time_str
        Or None if no available slots found
    """
    if start_date is None:
        start_date = datetime.now()
    
    # CRITICAL: Check rounding condition on ORIGINAL timestamp BEFORE adding buffer
    # This ensures we catch times that need rounding (minutes != 0)
    needs_rounding = start_date.minute != 0
    
    # Add 2-hour buffer for travel/prep
    min_slot_time = start_date + timedelta(hours=BUFFER_HOURS)
    
    # If original had minutes, we need to round up to next hour
    if needs_rounding:
        min_slot_time = min_slot_time.replace(minute=0, second=0, microsecond=0)
        min_slot_time += timedelta(hours=1)
    else:
        # Already on the hour, just truncate
        min_slot_time = min_slot_time.replace(minute=0, second=0, microsecond=0)
    
    # Search ahead for available slots
    end_time = start_date + timedelta(hours=hours_to_check)
    current = min_slot_time
    
    while current < end_time:
        if _is_time_allowed(current):
            # Found available slot
            end_slot = current + timedelta(hours=1)
            return {
                "start_time": current.isoformat(),
                "end_time": end_slot.isoformat(),
                "day_name": current.strftime("%A"),
                "time_str": current.strftime("%A at %I:%M %p")
            }
        
        # Move to next hour
        current += timedelta(hours=1)
    
    return None


def get_all_events() -> list[dict]:
    """Get all upcoming events from Google Calendar."""
    if not GOOGLE_AVAILABLE:
        return []
    
    creds = _get_credentials()
    if not creds:
        return []
    
    try:
        service = build("calendar", "v3", credentials=creds)
        now = datetime.utcnow().isoformat() + "Z"
        
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        
        return events_result.get("items", [])
    except Exception as e:
        print(f"⚠️  Error retrieving calendar events: {e}")
        return []


def create_event(
    title: str,
    notes: str = "",
    start_time: str = None,
    end_time: str = None,
    attendees: list = None,
    tenant_id: str = "",
    tenant_phone: str = "",
    is_emergency: bool = False
) -> bool:
    """
    Create event on Google Calendar.
    
    Args:
        title: Event title
        notes: Event description/notes
        start_time: ISO format start time
        end_time: ISO format end time
        attendees: List of attendee email addresses
        tenant_id: Tenant database ID
        tenant_phone: Tenant phone number
        is_emergency: Whether this is an emergency event
    
    Returns:
        True if successful, False otherwise
    """
    if not GOOGLE_AVAILABLE:
        print(f"[Calendar Event] (Google not available) {title}")
        return False
    
    creds = _get_credentials()
    if not creds:
        print(f"[Calendar Event] (No credentials) {title}")
        return False
    
    try:
        service = build("calendar", "v3", credentials=creds)
        
        event = {
            "summary": title,
            "description": notes,
            "start": {
                "dateTime": start_time or datetime.now().isoformat(),
                "timeZone": "America/Chicago"  # REQUIRED for Google Calendar API
            },
            "end": {
                "dateTime": end_time or (datetime.now() + timedelta(hours=1)).isoformat(),
                "timeZone": "America/Chicago"  # REQUIRED for Google Calendar API
            }
        }
        
        # Only add attendees if list is not empty
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees]
        
        # Add custom properties for property assistant
        event["extendedProperties"] = {
            "private": {
                "tenant_id": tenant_id,
                "tenant_phone": tenant_phone,
                "is_emergency": str(is_emergency),
                "created_by": "property_assistant"
            }
        }
        
        print(f"[DEBUG] Creating calendar event: {title}")
        print(f"[DEBUG] Start: {start_time}, End: {end_time}")
        print(f"[DEBUG] Calendar ID: {GOOGLE_CALENDAR_ID}")
        
        result = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        print(f"✓ Calendar event created: {title} ({result.get('id', 'unknown')})")
        return True
        
    except Exception as e:
        print(f"✗ Failed to create calendar event: {e}")
        import traceback
        traceback.print_exc()
        return False


def delete_event(event_id: str) -> bool:
    """Delete an event from Google Calendar."""
    if not GOOGLE_AVAILABLE:
        return False
    
    creds = _get_credentials()
    if not creds:
        return False
    
    try:
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        print(f"✓ Event deleted: {event_id}")
        return True
    except Exception as e:
        print(f"✗ Failed to delete event: {e}")
        return False
