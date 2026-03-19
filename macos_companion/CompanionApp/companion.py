import sys
import ctypes
import ctypes.util
import os
import time

def check_and_request_permission():
    if sys.platform != "darwin":
        return True

    try:
        # Load CoreGraphics framework
        cg_path = ctypes.util.find_library("CoreGraphics")
        if not cg_path:
            return False
        
        CG = ctypes.cdll.LoadLibrary(cg_path)

        # bool CGPreflightScreenCaptureAccess(void);
        CG.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        CG.CGPreflightScreenCaptureAccess.argtypes = []

        # bool CGRequestScreenCaptureAccess(void);
        CG.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        CG.CGRequestScreenCaptureAccess.argtypes = []

        # 1. Check if we already have it
        has_access = CG.CGPreflightScreenCaptureAccess()
        if has_access:
            print("[OK] Screen Recording permission: Granted")
            return True

        # 2. We don't have it, request it
        print("[!!] Screen Recording permission required.")
        print("     Triggering macOS permission prompt...")
        
        # This triggers the popup
        CG.CGRequestScreenCaptureAccess()

        # Give the user a moment to see the prompt
        print("[>>] Please click 'Open System Settings' and grant permission to 'Student Companion'.")
        print("     Once granted, YOU MUST RESTART this app.")
        return False

    except Exception as e:
        print(f"[FAIL] Could not verify macOS permissions: {e}")
        return False

if __name__ == "__main__":
    if sys.platform != "darwin":
        print("This script is only for macOS.")
        sys.exit(0)
        
    print("\n--- Student Companion: macOS Privacy Manager ---")
    if check_and_request_permission():
        print("\nAll permissions verified. Companion is ready.")
        # Keep alive for a bit to show the message if run directly
        time.sleep(3)
        sys.exit(0)
    else:
        # Keep open so user can read message
        print("\nWaiting for permission...")
        time.sleep(10)
        sys.exit(1)
