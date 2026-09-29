import threading
import time

import numpy as np

from vision_input.capture import Frame, LatestSlot


def _f(seq: int) -> Frame:
    return Frame(seq, np.zeros((2, 2, 3), np.uint8), time.monotonic(), time.time())


def test_consumer_always_gets_newest_and_drops_are_counted():
    s = LatestSlot()
    for i in range(1, 6):
        s.put(_f(i))
    got = s.wait_newer(-1, timeout=0.1)
    assert got is not None and got.seq == 5
    assert s.dropped == 4  # 1..4 는 읽히기 전에 덮어써짐


def test_wait_newer_times_out_without_new_frame():
    s = LatestSlot()
    s.put(_f(1))
    assert s.wait_newer(-1, 0.01).seq == 1
    t0 = time.monotonic()
    assert s.wait_newer(1, 0.05) is None
    assert time.monotonic() - t0 >= 0.04


def test_close_wakes_waiter_immediately():
    s = LatestSlot()
    out = []
    th = threading.Thread(target=lambda: out.append(s.wait_newer(-1, 5.0)))
    th.start()
    time.sleep(0.02)
    t0 = time.monotonic()
    s.close()
    th.join(1.0)
    assert out == [None]
    assert time.monotonic() - t0 < 0.5


def test_concurrent_producer_consumer_sequence_is_monotonic():
    s = LatestSlot()
    n = 2000
    seen: list[int] = []

    def produce():
        for i in range(1, n + 1):
            s.put(_f(i))
        s.close()

    def consume():
        last = -1
        while True:
            f = s.wait_newer(last, 1.0)
            if f is None:
                if s.closed:
                    return
                continue
            seen.append(f.seq)
            last = f.seq

    c = threading.Thread(target=consume)
    p = threading.Thread(target=produce)
    c.start()
    p.start()
    p.join()
    c.join(2.0)
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    assert seen[-1] <= n
    # 소비된 수 + 버려진 수 = 생산된 수 (마지막 프레임은 소비됐거나 남아 있음)
    assert len(seen) + s.dropped in (n, n - 1)


def test_wait_consumed_unblocks_after_read():
    s = LatestSlot()
    s.put(_f(1))
    assert not s.wait_consumed(1, 0.01)
    s.wait_newer(-1, 0.01)
    assert s.wait_consumed(1, 0.01)
