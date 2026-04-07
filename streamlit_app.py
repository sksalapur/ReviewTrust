import os
import sys
import uvicorn
import threading
import subprocess

# Add backend directory to Python path so app.py can import its modules
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

# Ensure playwright browsers are installed before starting using the active python (sys.executable)
print("Installing Playwright browsers...")
subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)

# Start FastAPI in a background thread
def run_fastapi():
    # We can still point uvicorn to backend.app:app, but now sys.path is correct
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000)

thread = threading.Thread(target=run_fastapi, daemon=True)
thread.start()

import streamlit as st
st.title("🛡️ ReviewTrust Backend Data Server")
st.success("FastAPI Backend is running efficiently in the background on port 8000!")

st.markdown("""
### Status: Online ✅
The backend is actively serving API requests to the mobile client.
- **Endpoint:** `/analyze`
- **Method:** `POST`

Streamlit is currently acting as the cloud host for the background FastAPI process to utilize its 1GB RAM allowance and robust system dependencies for Playwright automation.
""")
