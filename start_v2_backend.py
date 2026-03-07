import os
import subprocess
import sys

from pathlib import Path

# Ensure V2 root
V2_ROOT = Path(__file__).resolve().parent
os.chdir(V2_ROOT)

env = os.environ.copy()
env["PORT"] = "8080"

print(">>> STARTING V2 BACKEND VIA LAUNCHER (PORT 8080) <<<")
try:
    log_file = open("server.log", "a", encoding="utf-8")
    # Use 'py' to launch the production_launcher.py
    process = subprocess.Popen(
        [sys.executable, "production_launcher.py"],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    print(f"[INFO] Backend process started (PID: {process.pid}). Logs at server.log")
            
    # We leave the process running. In an agentic environment, 
    # the process will continue as long as the command is active.
    # However, since we want to return control, we'll let it run.
    
except Exception as e:
    print(f"Error starting backend: {e}")
    sys.exit(1)
