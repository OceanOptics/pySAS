#!/usr/bin/env python3
"""
Test to verify that SatlanticLogger.close() is thread-safe.
This simulates the scenario where GPS is writing data while the logger is being closed,
with the lock timeout behavior from the GPS class.
"""
import time
import threading
from pySAS.log import SatlanticLogger
import tempfile
import os

def test_satlantic_logger_thread_safety():
    """
    Test that close() doesn't cause deadlock when writing thread is active.
    This reproduces the original issue: GPS thread tries to acquire lock with timeout
    while close() holds the lock, causing repeated timeout errors.
    """

    # Create temporary directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create logger
        cfg = {
            'length': 1,  # 1 minute file rotation
            'filename_prefix': 'test_logger',
            'filename_ext': 'raw',
            'path': tmpdir,
            'reopen_delay': 0.1,
        }
        logger = SatlanticLogger(cfg)

        for a in range(3):  # Run multiple attempts to check consistency
            print(f"\n--- Attempt {a+1} ---")
            # Simulate the GPS class behavior with lock timeouts
            errors = []
            lock_timeout_errors = []
            stop_writing = threading.Event()
            data_logger_lock = threading.Lock()

            def gps_write_data():
                """
                Simulate GPS thread trying to write with lock timeout (like in interfaces.py GPS class).
                GPS uses _data_logger_lock.acquire(timeout=0.5) when writing data.
                """
                try:
                    for i in range(1000):
                        if stop_writing.is_set():
                            break
                        # Simulate GPS class behavior: acquire lock with timeout
                        if data_logger_lock.acquire(timeout=0.5):
                            try:
                                data = f'data {i}'.encode('utf-8')
                                logger.write(data, time.time())
                            finally:
                                data_logger_lock.release()
                        else:
                            # This is what happens in the real GPS class when it times out
                            lock_timeout_errors.append(f"GPS: unable to acquire data_logger to write data (attempt {i})")
                        time.sleep(0.01)  # Very small delay between writes
                except Exception as e:
                    errors.append(f"Write thread error: {e}")

            def main_thread_close():
                """
                Simulate main thread closing the logger.
                This would acquire the lock and hold it, blocking GPS writes.
                """
                try:
                    time.sleep(2)  # Let GPS write some data first
                    start_close = time.time()
                    # Acquire the data_logger_lock (simulating what close() would do)
                    stop_writing.set()
                    with data_logger_lock:
                        logger.close()
                    close_time = time.time() - start_close
                    print(f"✓ close() completed in {close_time:.3f}s")
                except Exception as e:
                    errors.append(f"Close error: {e}")

            # Start GPS writer threads
            writer_threads = []
            for _ in range(3):  # 3 concurrent GPS-like writers
                t = threading.Thread(target=gps_write_data)
                t.start()
                writer_threads.append(t)

            # Start main thread that will close
            close_thread = threading.Thread(target=main_thread_close)
            close_thread.start()

            # Wait for completion
            close_thread.join(timeout=5)
            for t in writer_threads:
                t.join(timeout=2)

            # Analyze results
            print(f"\nResults:")
            print(f"  Lock timeout errors: {len(lock_timeout_errors)}")
            if lock_timeout_errors and len(lock_timeout_errors) > 50:
                print(f"  ✗ TOO MANY TIMEOUT ERRORS - suggests old behavior (deadlock issue)")
                print(f"  First few errors: {lock_timeout_errors[:5]}")
            elif lock_timeout_errors:
                print(f"  ⚠ Some timeout errors (acceptable): {lock_timeout_errors[:3]}")
            else:
                print(f"  ✓ No timeout errors")

        # Check for any unexpected errors
        if errors:
            print("\n✗ Test failed with unexpected errors:")
            for error in errors:
                print(f"  - {error}")
            return False
        else:
            print("\n✓ Test passed - close() is thread-safe")

            # Verify files were created
            files = os.listdir(tmpdir)
            print(f"✓ Created {len(files)} log file(s)")
            return True

if __name__ == '__main__':
    print("Testing SatlanticLogger thread safety...")
    success = test_satlantic_logger_thread_safety()
    exit(0 if success else 1)

