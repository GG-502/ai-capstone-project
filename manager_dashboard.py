"""
manager_dashboard.py — Streamlit dashboard for property manager.

Displays tenant interactions, calendar events, and system status.
Provides interface for testing the graph and managing pending tasks.
"""

import streamlit as st
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime

# Add files folder to path
sys.path.insert(0, str(Path(__file__).parent / "files"))

from app_graph import build_and_run_graph
from state import ConversationState
from nodes import PENDING_STORE, _save_pending_store
import google_calendar
import tenant_db


def run_graph_simulation(
    phone_number: str,
    message: str,
    previous_state: dict = None
) -> dict:
    """
    Run the graph with given input.
    
    Args:
        phone_number: Tenant phone number
        message: Message from tenant
        previous_state: Previous graph state (for multi-turn)
    
    Returns:
        Dict with graph result and full state
    """
    # Initialize state
    if previous_state:
        state = ConversationState(previous_state)
        state["message"] = message
    else:
        state = ConversationState(
            phone_number=phone_number,
            tenant_id=None,
            tenant_name=None,
            unit_label=None,
            address=None,
            identity_status="unresolved",
            message=message,
            history=[],
            category=None,
            resolution_path=None,
            response=None,
            _route=None,
        )
    
    # Run graph
    try:
        result = asyncio.run(build_and_run_graph(state))
        return {
            "full_state": dict(result),
            "identity_status": result.get("identity_status"),
            "category": result.get("category"),
            "response": result.get("response"),
            "_route": result.get("_route"),
            "resolution_path": result.get("resolution_path"),
            "calendar_event_created": result.get("calendar_event_created", False),
        }
    except Exception as e:
        return {
            "error": str(e),
            "identity_status": state.get("identity_status"),
            "response": f"Error processing message: {e}"
        }


def clear_pending_store_for_phone(phone_number: str):
    """Clear pending store entry for a phone number."""
    if phone_number in PENDING_STORE:
        del PENDING_STORE[phone_number]
        _save_pending_store(PENDING_STORE)


def main():
    st.set_page_config(page_title="Property Manager Dashboard", layout="wide")
    
    st.title("🏢 Property Manager Dashboard")
    st.markdown("**Text Agent** | Multi-Tenant Property Management System")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")
        test_phone = st.text_input("Test Phone Number", value="859-889-4456")
        
        st.divider()
        
        if st.button("🔄 Clear All Pending Store"):
            PENDING_STORE.clear()
            _save_pending_store(PENDING_STORE)
            st.success("Cleared!")
        
        if st.button("📋 View Pending Store"):
            st.json(PENDING_STORE)
    
    # Main area
    tabs = st.tabs(["💬 Chat Simulator", "📊 System Status", "📅 Calendar", "👥 Tenants"])
    
    # TAB 1: Chat Simulator
    with tabs[0]:
        st.subheader("Demo Chat Simulator")
        
        col1, col2 = st.columns(2)
        
        with col1:
            user_message = st.text_input(
                "Message from tenant:",
                placeholder="e.g., I need maintenance help"
            )
        
        with col2:
            if st.button("Send Message", use_container_width=True):
                if user_message:
                    with st.spinner("Processing..."):
                        result = run_graph_simulation(test_phone, user_message)
                        
                        if "error" not in result:
                            st.success("✅ Message processed")
                            
                            col_res1, col_res2 = st.columns(2)
                            with col_res1:
                                st.metric("Identity Status", result.get("identity_status", "Unknown"))
                            with col_res2:
                                st.metric("Category", result.get("category", "Unknown"))
                            
                            st.write("**Response:**")
                            st.info(result.get("response", "(No response)"))
                            
                            if result.get("calendar_event_created"):
                                st.success("📅 Calendar event created!")
                        else:
                            st.error(f"Error: {result['error']}")
        
        st.divider()
        
        # Show pending store
        st.subheader("Pending Store")
        st.json(PENDING_STORE)
    
    # TAB 2: System Status
    with tabs[1]:
        st.subheader("System Health")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Tenants", len(tenant_db.get_all_tenants()))
        
        with col2:
            st.metric("Pending Confirmations", len(PENDING_STORE))
        
        with col3:
            st.metric("Calendar Available", "✓" if google_calendar.GOOGLE_AVAILABLE else "✗")
        
        st.divider()
        
        st.subheader("Recent Activity")
        st.info("Activity log not yet implemented")
    
    # TAB 3: Calendar
    with tabs[2]:
        st.subheader("📅 Google Calendar")
        
        if google_calendar.GOOGLE_AVAILABLE:
            events = google_calendar.get_all_events()
            
            if events:
                st.success(f"Found {len(events)} upcoming events")
                for event in events[:10]:
                    title = event.get('summary', 'Untitled')
                    start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', 'N/A'))
                    st.write(f"• **{title}** — {start}")
            else:
                st.info("No upcoming events")
        else:
            st.warning("Google Calendar not available")
    
    # TAB 4: Tenants
    with tabs[3]:
        st.subheader("👥 Tenants")
        
        tenants = tenant_db.get_all_tenants()
        
        if tenants:
            for tenant in tenants[:20]:
                with st.expander(f"{tenant['name']} - {tenant['unit_label']}"):
                    st.write(f"**Address:** {tenant['address']}")
                    st.write(f"**Phone:** {tenant['phone_number']}")
                    st.write(f"**Tenant ID:** {tenant['tenant_id']}")
        else:
            st.info("No tenants found in database")


if __name__ == "__main__":
    main()
