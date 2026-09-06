"""True cross-process test spawning real CLI commands against real background host."""

import json
import os
import subprocess
import sys
import time

python_exe = sys.executable

print("Step 1: Start background controller via CLI")
p_start = subprocess.run([python_exe, "-m", "windows.cli", "start"], capture_output=True, text=True)
print("CLI start exit:", p_start.returncode, "stdout:", p_start.stdout.strip())
assert p_start.returncode == 0

print("Step 2: Query status via CLI")
p_status1 = subprocess.run([python_exe, "-m", "windows.cli", "--json", "status"], capture_output=True, text=True)
print("CLI status1 stdout:", p_status1.stdout.strip())
status1 = json.loads(p_status1.stdout)
owner_pid = status1.get("owner_pid")
assert owner_pid is not None
print(f"Verified active owner PID: {owner_pid}")

print("Step 3: Repeated Start via CLI")
p_start2 = subprocess.run([python_exe, "-m", "windows.cli", "start"], capture_output=True, text=True)
print("CLI repeated start stdout:", p_start2.stdout.strip())
assert p_start2.returncode == 0

print("Step 4: Query status again via CLI")
p_status2 = subprocess.run([python_exe, "-m", "windows.cli", "--json", "status"], capture_output=True, text=True)
status2 = json.loads(p_status2.stdout)
assert status2.get("owner_pid") == owner_pid
print("Owner PID remained constant across invocations!")

print("Step 5: Stop via CLI")
p_stop = subprocess.run([python_exe, "-m", "windows.cli", "stop"], capture_output=True, text=True)
print("CLI stop stdout:", p_stop.stdout.strip())
assert p_stop.returncode == 0

print("Step 6: Query status after stop")
p_status3 = subprocess.run([python_exe, "-m", "windows.cli", "--json", "status"], capture_output=True, text=True)
status3 = json.loads(p_status3.stdout)
assert status3.get("desired_state") == "STOPPED_BY_USER"
print("Desired state verified as STOPPED_BY_USER")

# Kill background host cleanly
import psutil
try:
    proc = psutil.Process(owner_pid)
    proc.terminate()
    proc.wait(timeout=2)
except Exception:
    pass
print("ALL CROSS-PROCESS VERIFICATIONS PASSED!")
