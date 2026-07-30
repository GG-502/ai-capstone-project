#!/usr/bin/env python3
"""Start ngrok tunnel and get public URL"""
import os
from dotenv import load_dotenv
from pyngrok import ngrok

# Load environment variables from .env file
load_dotenv()

# Set ngrok auth token from environment variable
ngrok_token = os.getenv("NGROK_AUTH_TOKEN")
if not ngrok_token:
    print("❌ ERROR: NGROK_AUTH_TOKEN not set in environment")
    print("   Please set: export NGROK_AUTH_TOKEN='your-token-here'")
    exit(1)

ngrok.set_auth_token(ngrok_token)

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
