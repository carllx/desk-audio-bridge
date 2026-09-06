"""macOS Subprocess-level singleton regression test verifying fail-closed exit code 2."""

import json
import subprocess
import sys
import time

python_exe = sys.executable

print("=== macOS Subprocess Singleton Regression Test ===")

# Step 1: Start real controller owner A via run
print("Step 1: Launching Mac Owner A...")
proc_a = subprocess.Popen(
    [python_exe, "-m", "macos.cli", "run"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

# Wait for Owner A to acquire lock and start IPC server
time.sleep(1.0)
assert proc_a.poll() is None, "Mac Owner A must be running!"
print(f"Owner A running actively with PID {proc_a.pid}")

# Step 2: Attempt to launch Owner B
print("Step 2: Launching Mac Owner B (must be rejected with code 2)...")
proc_b = subprocess.Popen(
    [python_exe, "-m", "macos.cli", "run"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

# Owner B must exit quickly with exit code 2
try:
    stdout_b, stderr_b = proc_b.communicate(timeout=3.0)
    exit_code_b = proc_b.returncode
    print(f"Owner B exited with code: {exit_code_b}")
    print(f"Owner B stderr: {stderr_b.strip()}")
    assert exit_code_b == 2, f"Expected Owner B exit code 2, got {exit_code_b}"
except subprocess.TimeoutExpired:
    proc_b.kill()
    raise AssertionError("Owner B hung or failed to fail-closed quickly!")

# Step 3: Verify Owner A is completely unaffected
print("Step 3: Checking Owner A remains active and in control...")
assert proc_a.poll() is None, "Owner A must remain unaffected by rejected Owner B!"

# Verify status via CLI
p_status = subprocess.run([python_exe, "-m", "macos.cli", "--json", "status"], capture_output=True, text=True, check=True)
status_data = json.loads(p_status.stdout)
assert status_data.get("owner_pid") == proc_a.pid, f"Owner PID in status must match Owner A PID ({proc_a.pid})"
print(f"Status confirms Owner A ({proc_a.pid}) is sole active owner.")

# Step 4: Shut down Owner A and verify a new owner can acquire the singleton
print("Step 4: Terminating Owner A and verifying new owner succeeds...")
proc_a.terminate()
proc_a.wait(timeout=3.0)
time.sleep(0.5)

proc_c = subprocess.Popen(
    [python_exe, "-m", "macos.cli", "run"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
time.sleep(1.0)
assert proc_c.poll() is None, "New Owner C must succeed after Owner A shutdown!"
print(f"New Owner C successfully acquired singleton (PID {proc_c.pid})")

# Clean up Owner C
proc_c.terminate()
proc_c.wait(timeout=3.0)
print("=== MACOS SUBPROCESS SINGLETON REGRESSION TEST PASSED! ===")
