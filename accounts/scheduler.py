import threading
import time
import urllib.request


def run_keep_awake():
    """Pings the homepage every 10 minutes so PythonAnywhere keeps the app awake.

    Daily reminders are no longer sent from the server: the app schedules them on the
    phone (Settings → Reminders), so they work offline too.
    """
    while True:
        try:
            urllib.request.urlopen("https://espere.in/", timeout=10)
        except Exception as e:
            print(f"Self-ping failed: {e}")
        time.sleep(600)


def start_background_tasks():
    thread = threading.Thread(target=run_keep_awake, daemon=True)
    thread.start()
