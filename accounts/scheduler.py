import threading
import time
import urllib.request
from datetime import datetime
from django.core.management import call_command

def run_scheduler():
    """Background loop to auto-send daily reminders at 10 AM and 10 PM."""
    last_ping_time = time.time()
    
    while True:
        now = datetime.now()
        
        # 1. Check for reminder time
        if now.hour in (10, 22) and now.minute == 0:
            try:
                call_command("send_daily_reminders")
            except Exception as e:
                print(f"Auto-scheduler error: {e}")
            
            # Sleep 61 seconds so it doesn't trigger again in the same minute
            time.sleep(61)
            continue
            
        # 2. Prevent sleep by pinging the homepage every 10 minutes (600 seconds)
        current_time = time.time()
        if (current_time - last_ping_time) > 600:
            try:
                # This simulates a real visitor hitting your domain to keep PythonAnywhere awake
                urllib.request.urlopen("https://espere.in/", timeout=10)
            except Exception as e:
                print(f"Self-ping failed: {e}")
            last_ping_time = current_time

        # Check every 30 seconds
        time.sleep(30)

def start_auto_reminders():
    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()
