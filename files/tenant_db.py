"""
tenant_db.py — SQLite database access for tenant information.

Loads tenant data from schema.sql and provides query functions.
"""

import sqlite3
from pathlib import Path
from typing import Optional

# Database path
DB_PATH = Path(__file__).parent.parent / "property_assistant.db"


def normalize_phone_number(phone: str) -> str:
    """Normalize phone number to standard format (###-###-####)."""
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    
    # If 10 digits, format as ###-###-####
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    
    # If 11 digits starting with 1, remove leading 1 and format
    elif len(digits) == 11 and digits.startswith('1'):
        return f"{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    
    # Otherwise return as-is
    return phone


def get_connection():
    """Get database connection."""
    return sqlite3.connect(DB_PATH)


def get_tenant_by_phone(phone: str) -> Optional[dict]:
    """
    Get tenant by phone number.
    
    Args:
        phone: Phone number in any format
        
    Returns:
        Tenant dict or None if not found
    """
    normalized = normalize_phone_number(phone)
    
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT tenant_id, name, unit_label, address, phone_number FROM tenants WHERE phone_number = ?",
            (normalized,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def find_tenants_by_name_or_unit(query: str) -> list[dict]:
    """
    Find tenants by name or unit number (loose match).
    
    Args:
        query: Search query (name or unit number)
        
    Returns:
        List of matching tenant dicts
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Case-insensitive search on name or unit
        search_term = f"%{query.lower()}%"
        cursor.execute(
            """SELECT tenant_id, name, unit_label, address, phone_number FROM tenants 
               WHERE LOWER(name) LIKE ? OR LOWER(unit_label) LIKE ?""",
            (search_term, search_term)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_all_tenants() -> list[dict]:
    """Get all tenants from database."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT tenant_id, name, unit_label, address, phone_number FROM tenants")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_tenant_by_id(tenant_id: str) -> Optional[dict]:
    """Get tenant by ID."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT tenant_id, name, unit_label, address, phone_number FROM tenants WHERE tenant_id = ?",
            (tenant_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()
