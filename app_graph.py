"""
app_graph.py — Core graph building and execution logic.

Separated from CLI so it can be used by both app.py (CLI) and twilio_webhook.py.
"""

import os
import sys
import re
import importlib.util
from pathlib import Path
from typing import Literal
from datetime import datetime, timedelta
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START
from langgraph.types import Command

# Add files folder to path
sys.path.insert(0, str(Path(__file__).parent / "files"))

from state import ConversationState  # type: ignore
from nodes import resolve_identity  # type: ignore
from tenant_db import get_tenant_by_phone, find_tenants_by_name_or_unit, get_all_tenants  # type: ignore
from weather import get_current_conditions, is_freezing, get_weather_alert  # type: ignore

# Import Twilio for SMS
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_API_KEY")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+15026608679")
    TWILIO_CLIENT = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None
except ImportError:
    print("⚠️  Twilio not available")
    TWILIO_CLIENT = None

# Import Google Calendar module
try:
    import google_calendar
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    print("⚠️  Google Calendar module not available. Using fallback.")
    GOOGLE_CALENDAR_AVAILABLE = False

load_dotenv()

# Configuration
PROPERTY_MANAGER_PHONE = os.getenv("PROPERTY_MANAGER_PHONE", "+15028076153")
MANAGER_PHONE_NUMBER = os.getenv("MANAGER_PHONE_NUMBER", "555-0001")
ALLOWED_DAYS = ["Monday", "Tuesday", "Thursday"]
ALLOWED_HOURS = (8, 17)
HOURS_NOTICE = 24

# LLM for categorization (optional; falls back to keyword matching)
try:
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    if GITHUB_TOKEN:
        LLM = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.3,
            base_url="https://models.github.ai/inference",
            api_key=SecretStr(GITHUB_TOKEN)
        )
    else:
        LLM = None
except Exception:
    LLM = None

# Emergency keywords
EMERGENCY_KEYWORDS = {
    "gas": ["gas", "smell"],
    "fire": ["fire", "smoke", "burning"],
    "flood": ["flood", "water", "leak", "burst"],
    "no heat": ["no heat", "heat off", "heating", "cold"],
}

# ==================== NODES ====================

def route_by_sender(state: ConversationState) -> ConversationState:
    """Mark routing decision in state."""
    # Check if this is property manager
    if state["phone_number"] == PROPERTY_MANAGER_PHONE:
        # Check for pending weather approval
        from files.nodes import PENDING_STORE
        pending_weather = PENDING_STORE.get("weather", {})
        
        if pending_weather.get("context") == "awaiting_weather_approval":
            state["_route"] = "weather_response_handler"
        else:
            state["_route"] = "weather_approval"
    else:
        state["_route"] = "resolve_identity"
    return state


def _route_by_sender_decision(state: ConversationState) -> Literal["weather_approval", "weather_response_handler", "resolve_identity"]:
    """Routing function for sender."""
    return state.get("_route", "resolve_identity")


def resolve_identity_node(state: ConversationState) -> ConversationState:
    """Resolve tenant identity."""
    result = resolve_identity(state)
    return result


def check_identity_status(state: ConversationState) -> ConversationState:
    """
    Check if identity is confirmed.
    If not confirmed, set response and stop processing.
    If confirmed, proceed to emergency check.
    """
    if state["identity_status"] != "confirmed":
        # Identity not yet confirmed - don't proceed further
        # The response from resolve_identity will ask for confirmation
        state["_route"] = "end_and_wait"
    else:
        # Identity confirmed - proceed to emergency check
        state["_route"] = "emergency_check"
    
    return state


def _route_identity_check(state: ConversationState) -> Literal["emergency_check", "__end__"]:
    """Route based on identity confirmation status."""
    if state["identity_status"] != "confirmed":
        return "__end__"  # Wait for next message
    return "emergency_check"


def emergency_check(state: ConversationState) -> ConversationState:
    """Check for emergency keywords and weather."""
    message_lower = state["message"].lower()
    
    # Check keywords
    for category, keywords in EMERGENCY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                state["category"] = "emergency"
                state["_route"] = "emergency_handler"
                return state
    
    # Check weather
    if "heat" in message_lower or "cold" in message_lower or "freezing" in message_lower:
        conditions = get_current_conditions()
        temp = conditions["temperature"]
        if is_freezing(temp):
            state["category"] = "emergency"
            state["_route"] = "emergency_handler"
            return state
    
    state["_route"] = "categorize"
    return state


def categorize_node(state: ConversationState) -> ConversationState:
    """Categorize as maintenance or general."""
    message = state["message"]
    
    if LLM:
        try:
            from langchain_core.messages import HumanMessage
            prompt = f"""Categorize this tenant message as either 'maintenance' or 'general'.
Maintenance = repair issues, scheduling, broken things, plumbing, heating, appliances
General = other inquiries, questions, comments
Message: "{message}"
Respond with ONLY the category word: maintenance or general"""
            response = LLM.invoke([HumanMessage(content=prompt)])
            category_text = str(response.content).strip().lower()
            
            if "maintenance" in category_text:
                state["category"] = "maintenance"
            else:
                state["category"] = "general"
            return state
        except Exception:
            pass
    
    # Fallback to keywords
    message_lower = message.lower()
    maintenance_keywords = ["fix", "broken", "repair", "schedule", "maintenance", "issue", 
                           "problem", "dripping", "draining", "leak", "heat", "cold", "door",
                           "lock", "plumb", "electric", "appliance"]
    
    if any(keyword in message_lower for keyword in maintenance_keywords):
        state["category"] = "maintenance"
    else:
        state["category"] = "general"
    
    return state


def route_by_category(state: ConversationState) -> ConversationState:
    """Route to handler based on category and resolution path."""
    message = state.get("message", "").strip()
    
    # Check if we're waiting for maintenance option response (from pending store)
    from files.nodes import PENDING_STORE
    phone = state.get("phone_number")
    pending = PENDING_STORE.get(phone, {})
    mode = pending.get("mode", "")
    
    # Check if this is a response to maintenance options (1 or 2)
    if mode == "maintenance_option" and message in ["1", "2"]:
        if message == "2":
            state["_route"] = "callback_handler"
        elif message == "1":
            state["_route"] = "schedule_handler"
        return state
    
    # Check if we're waiting for schedule details (has schedule keywords)
    if state.get("resolution_path") == "awaiting_schedule":
        schedule_keywords = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                           "morning", "afternoon", "evening", "tomorrow", "next", "o'clock", "am", "pm"]
        if any(keyword in message.lower() for keyword in schedule_keywords):
            state["_route"] = "schedule_handler"
            return state
    
    # Standard category routing
    if state.get("category") == "maintenance":
        state["_route"] = "maintenance_handler"
    else:
        state["_route"] = "general_handler"
    return state


def _route_by_category_decision(state: ConversationState) -> Literal["maintenance_handler", "general_handler", "callback_handler", "schedule_handler"]:
    """Routing function for category."""
    return state.get("_route", "general_handler")


def maintenance_handler(state: ConversationState) -> ConversationState:
    """Handle maintenance requests."""
    from files.nodes import PENDING_STORE, _save_pending_store
    
    state["resolution_path"] = "pending"
    state["response"] = (
        "I can help you schedule a maintenance visit or have someone call you back.\n\n"
        "Please reply:\n"
        "1 - Schedule a time\n"
        "2 - Request a callback"
    )
    
    # Store that we're awaiting maintenance option response (1 or 2)
    phone = state.get("phone_number")
    if phone:
        PENDING_STORE[phone] = {
            "mode": "maintenance_option",
            "original_message": state.get("message", "")
        }
        _save_pending_store(PENDING_STORE)
    
    return state


def callback_handler(state: ConversationState) -> ConversationState:
    """Handle callback requests from tenants."""
    from datetime import datetime
    
    tenant_info = get_tenant_by_phone(state["phone_number"]) if state["phone_number"] else None
    tenant_name = tenant_info.get("name", "Unknown") if tenant_info else "Unknown"
    tenant_address = tenant_info.get("address", "Unknown") if tenant_info else "Unknown"
    tenant_phone = state["phone_number"]
    
    # Timestamp when callback was confirmed
    callback_time = datetime.now()
    callback_time_str = callback_time.strftime("%A, %B %d, %Y at %I:%M %p")
    
    # Get the original maintenance issue from pending store
    from files.nodes import PENDING_STORE
    pending = PENDING_STORE.get(state["phone_number"], {})
    original_issue = pending.get("original_message", "Maintenance callback requested")
    
    state["response"] = (
        f"Thank you, {tenant_name}! We've logged your callback request.\n\n"
        f"Our team will contact you at {tenant_phone} shortly to schedule the maintenance.\n"
        f"Callback Request Time: {callback_time_str}"
    )
    
    # Create calendar event for callback
    if GOOGLE_CALENDAR_AVAILABLE:
        # Event is for property manager to call tenant back ASAP
        event_notes = (
            f"CALLBACK REQUEST\n\n"
            f"Tenant: {tenant_name}\n"
            f"Phone: {tenant_phone}\n"
            f"Address: {tenant_address}\n"
            f"Issue: {original_issue}\n"
            f"Callback Requested: {callback_time_str}\n\n"
            f"Action: Call tenant to schedule maintenance appointment"
        )
        
        event_title = f"📞 Callback: {tenant_name} - {original_issue[:30]}"
        google_calendar.create_event(
            title=event_title,
            notes=event_notes,
            start_time=callback_time.isoformat(),
            end_time=(callback_time + timedelta(minutes=15)).isoformat(),
            attendees=[],
            tenant_id=state.get("tenant_id", ""),
            tenant_phone=tenant_phone
        )
        
        # Track that calendar event was created
        state["calendar_event_created"] = True
        state["calendar_event_title"] = event_title
        state["calendar_event_type"] = "callback"
    
    # Clear pending store now that callback is logged
    phone = state["phone_number"]
    from files.nodes import PENDING_STORE as PS, _save_pending_store
    if phone in PS:
        del PS[phone]
        _save_pending_store(PS)
    
    state["resolution_path"] = "callback_scheduled"
    return state


def schedule_handler(state: ConversationState) -> ConversationState:
    """Handle scheduling requests from tenants."""
    # Get tenant info for calendar event if they're providing schedule details
    message = state.get("message", "").strip()
    tenant_info = get_tenant_by_phone(state["phone_number"]) if state["phone_number"] else None
    tenant_name = tenant_info.get("name", "Unknown") if tenant_info else "Unknown"
    
    # Check if this is a schedule response (contains day/time info) rather than just option selection
    schedule_keywords = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                        "morning", "afternoon", "evening", "tomorrow", "next", "o'clock", "am", "pm"]
    has_schedule = any(keyword in message.lower() for keyword in schedule_keywords)
    
    if has_schedule and GOOGLE_CALENDAR_AVAILABLE and tenant_info:
        # Create calendar event for the scheduled maintenance
        from datetime import datetime, timedelta
        
        # Get original issue from pending store
        from files.nodes import PENDING_STORE
        pending = PENDING_STORE.get(state["phone_number"], {})
        original_issue = pending.get("original_message", "Maintenance scheduled")
        
        # Create event (scheduled for tomorrow at 10am as placeholder)
        scheduled_time = datetime.now() + timedelta(days=1)
        scheduled_time = scheduled_time.replace(hour=10, minute=0, second=0, microsecond=0)
        
        event_title = f"🔧 Maintenance: {tenant_name} - {original_issue[:30]}"
        event_notes = (
            f"SCHEDULED MAINTENANCE\n\n"
            f"Tenant: {tenant_name}\n"
            f"Phone: {state.get('phone_number')}\n"
            f"Address: {tenant_info.get('address', 'Unknown')}\n"
            f"Issue: {original_issue}\n"
            f"Requested Time: {message}\n\n"
            f"Action: Confirm appointment time with tenant"
        )
        
        google_calendar.create_event(
            title=event_title,
            notes=event_notes,
            start_time=scheduled_time.isoformat(),
            end_time=(scheduled_time + timedelta(minutes=60)).isoformat(),
            attendees=[],
            tenant_id=state.get("tenant_id", ""),
            tenant_phone=state.get("phone_number")
        )
        
        # Track that calendar event was created
        state["calendar_event_created"] = True
        state["calendar_event_title"] = event_title
        state["calendar_event_type"] = "schedule_confirmation"
    
    # If just asking for schedule, show prompt
    if not has_schedule:
        state["response"] = (
            "Great! Let's find a time that works for you.\n\n"
            "What days and times work best? "
            "(e.g., 'Monday afternoon', 'tomorrow morning', 'next Tuesday')"
        )
        state["resolution_path"] = "awaiting_schedule"
    else:
        state["response"] = (
            f"Perfect! We've scheduled a maintenance appointment based on your availability.\n\n"
            f"Preferred Time: {message}\n"
            f"We'll confirm the exact time shortly.\n\n"
            f"Thank you, {tenant_name}!"
        )
        state["resolution_path"] = "schedule_confirmed"
    
    return state


def general_handler(state: ConversationState) -> ConversationState:
    """Handle general inquiries."""
    tenant_info = get_tenant_by_phone(state["phone_number"]) if state["phone_number"] else None
    
    if LLM and tenant_info:
        try:
            from langchain_core.messages import HumanMessage
            prompt = f"""You are a helpful property management assistant. 
A tenant has sent a message. Provide a brief, friendly, helpful response.
Tenant: {tenant_info.get('name', 'Valued Tenant')}
Unit: {tenant_info.get('unit_label', 'N/A')} at {tenant_info.get('address', 'N/A')}
Message: "{state['message']}"
Keep response to 2-3 sentences. Be friendly and professional."""
            response = LLM.invoke([HumanMessage(content=prompt)])
            state["response"] = str(response.content).strip()
            return state
        except Exception:
            pass
    
    state["response"] = _default_general_response(tenant_info)
    return state


def emergency_handler(state: ConversationState) -> ConversationState:
    """Handle emergencies."""
    state["response"] = (
        "🚨 EMERGENCY DETECTED\n\n"
        "This is a priority issue. I'm immediately alerting the property manager. "
        "If this is life-threatening (fire, gas smell), call 911 first.\n\n"
        "Manager has been notified and will contact you shortly."
    )
    state["category"] = "emergency"
    
    tenant_info = get_tenant_by_phone(state["phone_number"]) if state["phone_number"] else None
    tenant_name = tenant_info.get("name", "Unknown") if tenant_info else "Unknown"
    
    # Create calendar event for emergency
    if GOOGLE_CALENDAR_AVAILABLE:
        event_title = f"⚠️  EMERGENCY: {tenant_name} - {state['message'][:40]}"
        google_calendar.create_event(
            title=event_title,
            notes=f"Tenant: {tenant_name}\nPhone: {state['phone_number']}\nMessage: {state['message']}",
            attendees=["manager"],
            tenant_phone=state["phone_number"],
            is_emergency=True
        )
        
        # Track that calendar event was created
        state["calendar_event_created"] = True
        state["calendar_event_title"] = event_title
        state["calendar_event_type"] = "emergency"
    
    return state


def weather_approval_node(state: ConversationState) -> ConversationState:
    """
    Check for severe weather and send draft alert to property manager.
    Alert is NOT sent until PM confirms via SMS reply.
    """
    # Check for weather alert
    alert = get_weather_alert()
    
    if not alert:
        # No severe weather
        state["response"] = "Weather conditions are normal. No alert needed."
        return state
    
    # Store alert in pending store for PM response handling
    from files.nodes import PENDING_STORE, _save_pending_store
    
    pending = {
        "context": "awaiting_weather_approval",
        "alert": alert,
        "timestamp": datetime.now().isoformat()
    }
    PENDING_STORE["weather"] = pending
    _save_pending_store(PENDING_STORE)
    
    # Send draft to property manager
    draft_message = (
        f"[DRAFT WEATHER ALERT]\n\n"
        f"Type: {alert['alert_type'].upper()}\n"
        f"Severity: {alert['severity'].upper()}\n\n"
        f"Conditions: {alert['conditions']['temperature']}°F, "
        f"{alert['conditions']['condition']}, "
        f"Wind: {alert['conditions']['wind_speed']}mph\n\n"
        f"Message:\n{alert['message']}\n\n"
        f"Reply: 1=SEND, 2=SKIP"
    )
    
    send_sms_to_pm(draft_message)
    
    state["response"] = (
        "Weather alert draft created and sent to Property Manager for approval.\n"
        "Awaiting response..."
    )
    state["_route"] = "weather_approval"
    return state


def weather_response_handler(state: ConversationState) -> ConversationState:
    """
    Handle property manager's response to weather alert.
    If 1: send to all tenants. If 2: skip.
    """
    message = state.get("message", "").strip()
    
    # Check if this is from the weather approval pending
    from files.nodes import PENDING_STORE, _save_pending_store
    pending = PENDING_STORE.get("weather", {})
    alert = pending.get("alert")
    
    if not alert:
        state["response"] = "No pending weather alert."
        return state
    
    if message == "1":
        # Send to all tenants
        alert_message = alert["message"]
        send_sms_to_all_tenants(alert_message)
        state["response"] = "Weather alert sent to all tenants."
    elif message == "2":
        state["response"] = "Weather alert skipped."
    else:
        state["response"] = "Invalid response. Reply: 1=SEND, 2=SKIP"
        return state
    
    # Clear pending
    if "weather" in PENDING_STORE:
        del PENDING_STORE["weather"]
        _save_pending_store(PENDING_STORE)
    
    return state


def send_sms_to_pm(message: str) -> bool:
    """Send SMS to property manager."""
    if not TWILIO_CLIENT:
        print(f"[SMS to PM] (Twilio not configured) {message}")
        return False
    
    try:
        msg = TWILIO_CLIENT.messages.create(
            body=message,
            from_=TWILIO_FROM_NUMBER,
            to=PROPERTY_MANAGER_PHONE
        )
        print(f"✓ SMS sent to PM ({PROPERTY_MANAGER_PHONE})")
        return True
    except Exception as e:
        print(f"✗ Failed to send SMS to PM: {e}")
        return False


def send_sms_to_all_tenants(message: str) -> int:
    """
    Send SMS to all tenants.
    Returns: number of messages sent
    """
    if not TWILIO_CLIENT:
        print(f"[SMS to Tenants] (Twilio not configured) {message}")
        return 0
    
    tenants = get_all_tenants()
    sent_count = 0
    
    for tenant in tenants:
        phone = tenant.get("phone_number")
        if not phone:
            continue
        
        # Format phone to E.164
        if not phone.startswith("+"):
            phone = "+1" + phone.replace("-", "").replace(".", "").replace(" ", "")
        
        try:
            msg = TWILIO_CLIENT.messages.create(
                body=message,
                from_=TWILIO_FROM_NUMBER,
                to=phone
            )
            sent_count += 1
            print(f"✓ Weather alert sent to {tenant.get('name')} ({phone})")
        except Exception as e:
            print(f"✗ Failed to send to {tenant.get('name')}: {e}")
    
    print(f"\n✓ Weather alerts sent to {sent_count} tenants")
    return sent_count


def _default_general_response(tenant_info=None) -> str:
    """Fallback response."""
    if tenant_info and isinstance(tenant_info, dict):
        return (
            f"Thank you for reaching out, {tenant_info.get('name', 'Valued Tenant')}. "
            f"A property manager will review your message and respond within 24 hours."
        )
    else:
        return (
            "Thank you for reaching out. A property manager will review your message "
            "and get back to you within 24 hours."
        )


# ==================== GRAPH ====================

def build_graph() -> StateGraph:
    """Build the LangGraph state machine."""
    builder = StateGraph(ConversationState)
    
    # Add nodes
    builder.add_node("route_by_sender", route_by_sender)
    builder.add_node("resolve_identity", resolve_identity_node)
    builder.add_node("check_identity", check_identity_status)
    builder.add_node("emergency_check", emergency_check)
    builder.add_node("categorize", categorize_node)
    builder.add_node("route_by_category", route_by_category)
    builder.add_node("maintenance_handler", maintenance_handler)
    builder.add_node("callback_handler", callback_handler)
    builder.add_node("schedule_handler", schedule_handler)
    builder.add_node("general_handler", general_handler)
    builder.add_node("emergency_handler", emergency_handler)
    builder.add_node("weather_approval", weather_approval_node)
    builder.add_node("weather_response_handler", weather_response_handler)
    
    # Edges
    builder.add_edge(START, "route_by_sender")
    builder.add_conditional_edges("route_by_sender", _route_by_sender_decision)
    builder.add_edge("resolve_identity", "check_identity")
    builder.add_conditional_edges("check_identity", _route_identity_check)
    builder.add_conditional_edges(
        "emergency_check",
        lambda state: "emergency_handler" if state.get("_route") == "emergency_handler" else "categorize"
    )
    builder.add_edge("emergency_handler", "__end__")
    builder.add_edge("categorize", "route_by_category")
    builder.add_conditional_edges("route_by_category", _route_by_category_decision)
    builder.add_edge("maintenance_handler", "__end__")
    builder.add_edge("callback_handler", "__end__")
    builder.add_edge("schedule_handler", "__end__")
    builder.add_edge("general_handler", "__end__")
    builder.add_edge("weather_approval", "__end__")
    builder.add_edge("weather_response_handler", "__end__")
    
    return builder.compile()


async def build_and_run_graph(initial_state: ConversationState) -> ConversationState:
    """Build and run the graph with given initial state."""
    graph = build_graph()
    result = graph.invoke(initial_state)
    return result
