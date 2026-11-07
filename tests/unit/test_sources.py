import threading
import time

import numpy as np
import pytest

from convergent.common.config import SourceConfig
from convergent.vision.preprocessing import FramePreprocessor, processing_to_original
from convergent.vision.sources import (
    LatestFrameQueue,
    NetworkFrame,
    NetworkSource,
    SourceError,
    SyntheticSource,
    VideoFileSource,
    create_source,
)


def test_synthetic_source_is_deterministic():
    cfg = SourceConfig(kind="synthetic", max_frames=10, target_fps=15, synthetic_seed=3)
    runs = []
    for _ in range(2):
        with create_source(cfg) as src:
            frames = list(src)
        runs.append([(f.frame_id, f.capture_ts, int(f.image.sum())) for f in frames])
    assert runs[0] == runs[1] and len(runs[0]) == 10


def test_decimation_uses_capture_timestamps():
    cfg = SourceConfig(kind="synthetic", max_frames=20, target_fps=10)  # synthetic runs at 30 fps internally
    with SyntheticSource(cfg) as src:
        frames = list(src)
    dts = np.diff([f.capture_ts for f in frames])
    assert np.allclose(dts, 0.1, atol=1e-6)
    assert src.stats.frames_skipped_decimation > 0


def test_video_file_source_timestamps_and_determinism(tiny_video):
    cfg = SourceConfig(kind="video", path=str(tiny_video), target_fps=30)
    ts_runs = []
    for _ in range(2):
        with VideoFileSource(cfg) as src:
            frames = list(src)
        ts_runs.append([(f.frame_id, round(f.capture_ts, 6), f.source_frame_index) for f in frames])
    assert ts_runs[0] == ts_runs[1]
    assert len(ts_runs[0]) == 30 and ts_runs[0][0][1] == 0.0
    assert all(b[1] > a[1] for a, b in zip(ts_runs[0], ts_runs[0][1:], strict=False))
    assert frames[0].timestamps.capture_clock in ("video_pts", "video_index")
    assert frames[0].width == 320 and frames[0].transform.original_width == 320


def test_video_source_decimated_to_target_fps(tiny_video):
    with VideoFileSource(SourceConfig(kind="video", path=str(tiny_video), target_fps=5)) as src:
        frames = list(src)
    assert 9 <= len(frames) <= 11
    assert np.allclose(np.diff([f.capture_ts for f in frames]), 0.2, atol=0.05)


def test_video_source_errors():
    with pytest.raises(SourceError):
        VideoFileSource(SourceConfig(kind="video", path=None))
    with pytest.raises(SourceError):
        VideoFileSource(SourceConfig(kind="video", path="/nonexistent/x.mp4")).open()


def test_preprocessor_resize_keeps_aspect_and_inverse_mapping():
    pre = FramePreprocessor(640, 480)
    img = np.zeros((720, 1280, 3), np.uint8)
    out, t = pre.apply(img)
    assert out.shape == (360, 640, 3)
    assert abs(t.scale_x - 0.5) < 1e-9 and t.original_width == 1280
    x, y = processing_to_original(320, 180, t)
    assert (x, y) == (640, 360)


def test_preprocessor_rotation_inverse_mapping():
    pre = FramePreprocessor(640, 480, rotation_deg=90)
    img = np.zeros((480, 640, 3), np.uint8)
    out, t = pre.apply(img)
    assert out.shape[:2] == (480, 360)  # rotated 640x480 -> 480x640 -> scaled to fit 640x480 height
    # top-left of the rotated frame corresponds to the bottom-left of the original
    x, y = processing_to_original(0, 0, t)
    assert abs(x - 0) < 1.0 and abs(y - 479) < 1.5
    with pytest.raises(ValueError):
        FramePreprocessor(640, 480, rotation_deg=30)


def test_latest_frame_queue_drops_oldest():
    q = LatestFrameQueue(2)
    for i in range(5):
        q.put(i)
    assert q.dropped == 3 and len(q) == 2
    assert q.get(0.01) == 3 and q.get(0.01) == 4 and q.get(0.01) is None
    q.close()
    assert q.get(0.01) is None


def test_network_source_push_and_disconnect():
    src = NetworkSource(SourceConfig(kind="network", width=64, height=48, target_fps=0), queue_size=2, read_timeout_s=0.2)
    src.set_device_id("pi-test")
    with src:
        for i in range(3):
            src.push(NetworkFrame(np.zeros((48, 64, 3), np.uint8), device_ts=i * 0.1, frame_index=i))
        f1 = src.read()
        assert f1 is not None and f1.source_frame_index == 1 and f1.source_id == "network:pi-test"
        f2 = src.read()
        assert f2.capture_ts == pytest.approx(0.2)
        assert src.read() is None  # timeout, no crash
        src.on_disconnect()  # device restarted its counter
        src.push(NetworkFrame(np.zeros((48, 64, 3), np.uint8), device_ts=0.0, frame_index=0))
        f3 = src.read()
        assert f3 is not None and f3.frame_id == 2  # pipeline frame ids keep increasing
    assert src.stats.frames_dropped_queue == 1


def test_network_source_rejects_out_of_order_frames():
    src = NetworkSource(SourceConfig(kind="network", width=16, height=16, target_fps=0), queue_size=8, read_timeout_s=0.1)
    with src:
        src.push(NetworkFrame(np.zeros((16, 16, 3), np.uint8), 1.0, 5))
        src.push(NetworkFrame(np.zeros((16, 16, 3), np.uint8), 0.5, 6))  # older timestamp
        src.push(NetworkFrame(np.zeros((16, 16, 3), np.uint8), 1.5, 7))
        got = [src.read(), src.read()]
    assert [g.capture_ts for g in got if g] == [1.0, 1.5]
    assert src.stats.frames_rejected_order == 1


def test_queue_blocking_get_wakes_on_put():
    q = LatestFrameQueue(1)
    out = []

    def consumer():
        out.append(q.get(2.0))

    t = threading.Thread(target=consumer)
    t.start()
    time.sleep(0.05)
    q.put("x")
    t.join(2.0)
    assert out == ["x"]
