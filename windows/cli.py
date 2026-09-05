"""Command line interface for desk-audio-bridge controller on Windows."""

import argparse
import json
import sys

from .bridge_common import ControllerStatus
from .controller import WindowsBridgeController


def main():
    parser = argparse.ArgumentParser(description="desk-audio-bridge Windows controller")
    parser.add_argument("command", choices=["start", "stop", "status", "reconcile"], help="Action to execute")
    parser.add_argument("--json", action="store_true", help="Output status in JSON format")

    args = parser.parse_args()
    controller = WindowsBridgeController()

    if args.command == "start":
        success = controller.start()
        print(f"Controller started (enabled={success})")
    elif args.command == "stop":
        success = controller.stop()
        print(f"Controller stopped (stopped={success})")
    elif args.command == "reconcile":
        controller.reconcile()
        print("Reconciliation triggered")
    elif args.command == "status":
        status: ControllerStatus = controller.get_status()
        if args.json:
            print(json.dumps(status.to_dict(), indent=2))
        else:
            print("=== desk-audio-bridge Controller Status ===")
            print(f"Controller State:      {status.controller_state}")
            print(f"Desired State:         {status.desired_state}")
            print(f"Host Role:             {status.role}")
            print(f"Peer Available:        {status.peer_available}")
            print(f"Peer Address:          {status.peer_address or 'None'}")
            print(f"Speaker Path State:    {status.speaker_path_state}")
            print(f"Speaker Port:          {status.speaker_target_port}")
            print(f"Owned Children Count:  {status.owned_children_count}")
            if status.last_actionable_error:
                print(f"Last Error:            {status.last_actionable_error}")


if __name__ == "__main__":
    main()
