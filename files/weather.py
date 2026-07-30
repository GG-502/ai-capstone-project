"""
weather.py — Weather API integration for alerts and conditions.

Provides weather-based alerts for property manager and conditions checks.
"""

import os
import requests
from datetime import datetime


def get_current_conditions() -> dict:
    """
    Get current weather conditions.
    
    Returns:
        Dict with keys: temperature, condition, humidity, wind_speed
    """
    try:
        # Using OpenWeatherMap API or similar
        # For now, return mock data if no API key configured
        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            return {
                "temperature": 72,
                "condition": "Partly Cloudy",
                "humidity": 55,
                "wind_speed": 8,
                "location": "Louisville, KY"
            }
        
        # Example: OpenWeatherMap API call
        # This would be replaced with actual API integration
        lat, lon = 38.2527, -85.7585  # Louisville, KY
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=imperial"
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                "temperature": data['main']['temp'],
                "condition": data['weather'][0]['main'],
                "humidity": data['main']['humidity'],
                "wind_speed": data['wind']['speed'],
                "location": data['name']
            }
    except Exception as e:
        print(f"⚠️  Weather API error: {e}")
    
    # Fallback
    return {
        "temperature": 72,
        "condition": "Unknown",
        "humidity": 50,
        "wind_speed": 0,
        "location": "Louisville, KY"
    }


def is_freezing(temperature: float) -> bool:
    """Check if temperature is freezing (<=32°F)."""
    return temperature <= 32


def get_weather_alert() -> dict | None:
    """
    Check for severe weather alerts.
    
    Returns:
        Alert dict or None if no alerts
    """
    conditions = get_current_conditions()
    temp = conditions.get("temperature", 72)
    condition = conditions.get("condition", "")
    
    # Check for severe conditions
    if is_freezing(temp):
        return {
            "alert_type": "freeze_warning",
            "severity": "high",
            "conditions": conditions,
            "message": f"❄️ FREEZE WARNING: Temperature is {temp}°F. Tenants should protect outdoor pipes and ensure heating systems are functioning."
        }
    
    if "tornado" in condition.lower() or "severe" in condition.lower():
        return {
            "alert_type": "severe_weather",
            "severity": "critical",
            "conditions": conditions,
            "message": f"⚠️ SEVERE WEATHER ALERT: {condition}. Please take shelter and check on tenants."
        }
    
    if "snow" in condition.lower():
        return {
            "alert_type": "snow_warning",
            "severity": "medium",
            "conditions": conditions,
            "message": f"❄️ SNOW WARNING: {condition}. Ensure parking areas and walkways are clear."
        }
    
    return None
