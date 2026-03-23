#!/usr/bin/env python3
"""
Camera identification script for Floor Piano.
Shows a preview window for each available camera so you can identify which is your USB webcam.
"""

import cv2
import time
import sys

def test_camera(camera_index):
    """Test a specific camera and show preview."""
    print(f"\nTesting Camera {camera_index}...")
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print(f"Camera {camera_index}: Not available")
        return False

    # Get camera properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    print(f"Camera {camera_index}: {width}x{height} @ {fps} FPS")

    # Show preview for 3 seconds
    print("Showing preview... (press any key in the window to continue)")
    start_time = time.time()

    while time.time() - start_time < 3:
        ret, frame = cap.read()
        if ret:
            # Add camera index label to the frame
            cv2.putText(frame, f"Camera {camera_index}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.imshow(f'Camera {camera_index} Preview', frame)

            # Break if user presses a key
            if cv2.waitKey(1) != -1:
                break
        else:
            print(f"Failed to read frame from camera {camera_index}")
            break

    cap.release()
    cv2.destroyAllWindows()
    return True

def main():
    print("Floor Piano - Camera Identification Tool")
    print("=========================================")
    print("This will test each camera and show a preview window.")
    print("Look at each preview to identify your USB webcam.")
    print("Note: You may need to grant camera permissions to the terminal app.")
    print()

    # Test cameras 0, 1, 2 (the ones that were detected)
    available_cameras = []

    for i in range(3):
        if test_camera(i):
            available_cameras.append(i)

    print("\nAvailable cameras:", available_cameras)
    print("\nWhich camera number is your USB webcam?")
    print("Update this number in config/defaults.json as the 'camera_source' value.")
    print("Then restart the Floor Piano application.")

if __name__ == "__main__":
    main()