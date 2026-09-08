#!/usr/bin/env python3
"""
Standalone camera availability test. Run this BEFORE the full application
to confirm OpenCV can see your MacBook's webcam.

Usage:
    python3 test_camera.py

What it does:
  1. Probes camera indexes 0-3, reporting AVAILABLE / NOT AVAILABLE.
  2. For the first available camera, opens a live preview window so you
     can visually confirm it's actually your webcam (press 'q' to quit).

If macOS blocks camera access, this script will tell you exactly what
to do (see the README's "macOS camera permissions" section too).
"""
import sys

import cv2


def probe_camera(index: int, timeout_frames: int = 5):
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        return None

    # Some backends report isOpened()==True but never deliver a frame;
    # confirm we can actually read before calling it AVAILABLE.
    for _ in range(timeout_frames):
        ret, frame = cap.read()
        if ret and frame is not None:
            h, w = frame.shape[:2]
            cap.release()
            return (w, h)
    cap.release()
    return None


def main():
    print("Scanning camera indexes 0-3...\n")
    available = []
    for idx in range(4):
        result = probe_camera(idx)
        if result:
            w, h = result
            print(f"Camera {idx}: AVAILABLE  ({w}x{h})")
            available.append(idx)
        else:
            print(f"Camera {idx}: NOT AVAILABLE")

    print()
    if not available:
        print("No cameras were detected.")
        print()
        print("If you're on macOS and this is the first time a terminal/Python")
        print("process has tried to use the camera, macOS likely blocked it silently.")
        print("Fix:")
        print("  1. Open System Settings")
        print("  2. Go to Privacy & Security -> Camera")
        print("  3. Enable the toggle for your terminal app (Terminal, iTerm2,")
        print("     or whichever app you launched Python from)")
        print("  4. If Python/Terminal isn't listed, run this script once more —")
        print("     macOS should prompt you for permission the first time")
        print("     cv2.VideoCapture actually tries to access the camera.")
        print("  5. Re-run: python3 test_camera.py")
        sys.exit(1)

    print(f"Using camera index {available[0]} as CAMERA 1 (event_entrance).")
    print("Opening a live preview window — press 'q' to close it.\n")

    cap = cv2.VideoCapture(available[0])
    if not cap.isOpened():
        print("Camera opened during scan but failed to reopen for preview. "
              "Try re-running the script.")
        sys.exit(1)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Warning: failed to read a frame from the camera.")
            break
        cv2.imshow("Camera Test - press q to quit", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Camera test complete.")


if __name__ == "__main__":
    main()
