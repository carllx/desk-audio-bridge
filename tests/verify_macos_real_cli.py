"""True cross-process test spawning real CLI commands on macOS and testing unrelated process protection."""

import json
import os
import subprocess
import sys
import time
import psutil

python_exe = sys.executable

print("=== True macOS CLI Cross-Process & Protection Test ===")

# Step 0: Start an unrelated external GStreamer process
gst_bin = "/Library/Frameworks/GStreamer.framework/Versions/1.0/bin/gst-launch-1.0"
print(f"Step 0: Starting unrelated external GStreamer process using {gst_bin}...")
unrelated_proc = subprocess.Popen(
    [gst_bin, "fakesrc", "is-live=true", "!", "fakesink"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
time.sleep(0.5)
assert unrelated_proc.poll() is None, "Unrelated GStreamer process must be running!"
unrelated_pid = unrelated_proc.pid
print(f"Unrelated GStreamer process running actively with PID {unrelated_pid}")

try:
    # Step 1: Start background controller via CLI
    print("Step 1: Start background controller via macos.cli start...")
    p_start = subprocess.run([python_exe, "-m", "macos.cli", "start"], capture_output=True, text=True)
    print("CLI start exit:", p_start.returncode, "stdout:", p_start.stdout.strip())
    assert p_start.returncode == 0

    # Step 2: Query status via CLI
    print("Step 2: Query status via macos.cli --json status...")
    p_status1 = subprocess.run([python_exe, "-m", "macos.cli", "--json", "status"], capture_output=True, text=True)
    print("CLI status1 stdout:", p_status1.stdout.strip())
    status1 = json.loads(p_status1.stdout)
    owner_pid = status1.get("owner_pid")
    assert owner_pid is not None
    assert status1.get("desired_state") == "ENABLED"
    assert status1.get("role") == "macos"
    print(f"Verified active owner PID: {owner_pid}")

    # Step 3: Repeated Start via CLI
    print("Step 3: Repeated Start via macos.cli start...")
    p_start2 = subprocess.run([python_exe, "-m", "macos.cli", "start"], capture_output=True, text=True)
    print("CLI repeated start stdout:", p_start2.stdout.strip())
    assert p_start2.returncode == 0

    # Step 4: Query status again via CLI
    print("Step 4: Query status again via macos.cli --json status...")
    p_status2 = subprocess.run([python_exe, "-m", "macos.cli", "--json", "status"], capture_output=True, text=True)
    status2 = json.loads(p_status2.stdout)
    assert status2.get("owner_pid") == owner_pid
    print("Owner PID remained constant across repeated Start invocations!")

    # Step 5: Stop via CLI
    print("Step 5: Stop via macos.cli stop...")
    p_stop = subprocess.run([python_exe, "-m", "macos.cli", "stop"], capture_output=True, text=True)
    print("CLI stop stdout:", p_stop.stdout.strip())
    assert p_stop.returncode == 0

    # Step 6: Query status after stop
    print("Step 6: Query status after stop...")
    p_status3 = subprocess.run([python_exe, "-m", "macos.cli", "--json", "status"], capture_output=True, text=True)
    status3 = json.loads(p_status3.stdout)
    assert status3.get("desired_state") == "STOPPED_BY_USER"
    print("Desired state verified as STOPPED_BY_USER")

    # Step 7: Critical Check - Verify unrelated GStreamer process remains alive and untouched!
    print("Step 7: Verifying unrelated GStreamer process is STILL running...")
    assert unrelated_proc.poll() is None, "Unrelated GStreamer process was wrongly terminated!"
    assert psutil.pid_exists(unrelated_pid), f"PID {unrelated_pid} must still exist!"
    print(f"SUCCESS: Unrelated GStreamer PID {unrelated_pid} was completely untouched by controller Stop!")

finally:
    # Cleanup background host cleanly
    if "owner_pid" in locals() and owner_pid:
        try:
            proc = psutil.Process(owner_pid)
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass

    # Cleanup unrelated proc
    try:
        unrelated_proc.terminate()
        unrelated_proc.wait(timeout=2)
    except Exception:
        pass

print("=== ALL MACOS CLI CROSS-PROCESS & PROTECTION VERIFICATIONS PASSED! ===")
