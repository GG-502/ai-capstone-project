"""
state.py — ConversationState TypedDict for LangGraph.

Holds all conversation context, identity info, and routing state.
"""

from typing import TypedDict, Optional


class ConversationState(TypedDict, total=False):
    """Conversation state for the property assistant graph."""
    
    # Incoming data
    phone_number: str
    message: str
    
    # Tenant identity (verified)
    tenant_id: Optional[str]
    tenant_name: Optional[str]
    unit_label: Optional[str]
    address: Optional[str]
    identity_status: str  # "unresolved", "pending_confirmation", "confirmed"
    
    # Conversation tracking
    history: list[dict]
    category: Optional[str]  # "emergency", "maintenance", "general"
    resolution_path: Optional[str]  # "pending", "callback_scheduled", "schedule_confirmed", etc.
    response: Optional[str]
    
    # Internal routing
    _route: Optional[str]
    
    # Calendar integration
    calendar_event_created: bool
    calendar_event_title: Optional[str]
    calendar_event_type: Optional[str]  # "callback", "schedule_confirmation", "emergency"
