"""
lease_reminder.py — Lease renewal reminder agent.

Monitors lease expiration dates and creates calendar reminders.
"""

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3


def check_upcoming_lease_expirations(days_ahead: int = 60) -> list[dict]:
    """
    Check for leases expiring within the specified days.
    
    Args:
        days_ahead: Number of days ahead to check (default 60)
    
    Returns:
        List of tenants with expiring leases
    """
    db_path = Path(__file__).parent.parent / "property_assistant.db"
    
    if not db_path.exists():
        return []
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        today = datetime.now().date()
        cutoff_date = today + timedelta(days=days_ahead)
        
        # Query leases expiring soon
        cursor.execute("""
            SELECT tenant_id, name, unit_label, address, lease_end_date
            FROM tenants
            WHERE lease_end_date IS NOT NULL
            AND date(lease_end_date) BETWEEN date(?) AND date(?)
            ORDER BY lease_end_date ASC
        """, (today, cutoff_date))
        
        rows = cursor.fetchall()
        results = [dict(row) for row in rows]
        conn.close()
        return results
        
    except Exception as e:
        print(f"⚠️  Error checking lease expirations: {e}")
        return []


def create_lease_reminder_event(tenant: dict, calendar_module) -> bool:
    """
    Create a calendar event for lease renewal reminder.
    
    Args:
        tenant: Tenant dict with lease_end_date
        calendar_module: Google Calendar module
    
    Returns:
        True if event created successfully
    """
    try:
        lease_date = datetime.fromisoformat(tenant["lease_end_date"])
        reminder_date = lease_date - timedelta(days=30)  # Remind 30 days before
        
        event_title = f"📋 Lease Renewal: {tenant['name']} - {tenant['unit_label']}"
        event_notes = f"""
Tenant: {tenant['name']}
Unit: {tenant['unit_label']}
Address: {tenant['address']}
Lease Expires: {lease_date.strftime('%B %d, %Y')}

Action: Contact tenant regarding lease renewal
"""
        
        return calendar_module.create_event(
            title=event_title,
            notes=event_notes,
            start_time=reminder_date.isoformat(),
            end_time=(reminder_date + timedelta(hours=1)).isoformat(),
            tenant_id=tenant.get("tenant_id", ""),
            attendees=["manager"]
        )
    except Exception as e:
        print(f"⚠️  Error creating lease reminder: {e}")
        return False


def scan_and_alert(calendar_module, days_ahead: int = 60) -> int:
    """
    Scan for upcoming lease expirations and create reminders.
    
    Returns:
        Number of reminder events created
    """
    expiring = check_upcoming_lease_expirations(days_ahead)
    created = 0
    
    for tenant in expiring:
        if create_lease_reminder_event(tenant, calendar_module):
            created += 1
    
    if created > 0:
        print(f"✓ Created {created} lease reminder(s)")
    
    return created
