#!/usr/bin/env python3
"""Start ngrok tunnel and get public URL"""
import os
from pyngrok import ngrok

# Set ngrok auth token
ngrok.set_auth_token("3HEVpy946ro5UWoWimMJpLDUm5v_5f7RcX68KHCdf6nrCkNb4")

try:
    # Start tunnel on port 5001
    public_url = ngrok.connect(5001, "http")
    print(f"\n🌐 PUBLIC URL: {public_url}\n")
    print("✅ Tunnel is running!")
    print("   Keep this terminal open for SMS webhooks to work")
    print("\n   Next: Configure Twilio webhook at:")
    print(f"   {public_url}/sms/incoming")
    
    # Keep tunnel running
    ngrok_process = ngrok.get_ngrok_process()
    ngrok_process.proc.wait()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
