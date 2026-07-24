from __future__ import annotations

import time

import pytest

from proxy_traffic_monitor.collector import Collector, ConnState, LiveConn


class DummyConfig:
    class collector:
        minute_flush_interval_sec = 60
        connlog_flush_interval_sec = 10
        cleanup_interval_hours = 24
        ws_reconnect_backoff_sec = [1]
    class storage:
        retention_days = 30


@pytest.fixture
def collector():
    return Collector(None, None, DummyConfig())


def test_classify_direction():
    assert Collector.classify_direction(["Proxy", "DIRECT"]) == "direct"
    assert Collector.classify_direction(["Proxy"]) == "proxy"
    assert Collector.classify_direction([]) == "proxy"


def _minute_ts(t):
    return int(t // 60 * 60)


def test_delta_and_minute_agg(collector):
    t1, t2 = 1000.0, 1060.0
    msg1 = {"connections": [{"id": "1", "upload": 10, "download": 20, "metadata": {}, "chains": ["DIRECT"], "rule": "MATCH"}]}
    msg2 = {"connections": [{"id": "1", "upload": 30, "download": 50, "metadata": {}, "chains": ["DIRECT"], "rule": "MATCH"}]}
    collector._process_snapshot(msg1, t1)
    collector._process_snapshot(msg2, t2)
    # Both timestamps fall into same minute bucket (1000//60*60 = 960, 1060//60*60 = 1020) or same
    key1 = (_minute_ts(t1), "未知", "direct")
    key2 = (_minute_ts(t2), "未知", "direct")
    # First snapshot: delta=0 (first seen), second: delta=20,30
    # They may be in same or different buckets depending on minute boundary
    total_up = collector.minute_agg.get(key1, [0, 0])[0] + collector.minute_agg.get(key2, [0, 0])[0]
    total_down = collector.minute_agg.get(key1, [0, 0])[1] + collector.minute_agg.get(key2, [0, 0])[1]
    assert total_up == 20
    assert total_down == 30


def test_counter_reset(collector):
    t1, t2 = 1000.0, 1060.0
    msg1 = {"connections": [{"id": "1", "upload": 100, "download": 100, "metadata": {}, "chains": ["DIRECT"], "rule": "MATCH"}]}
    msg2 = {"connections": [{"id": "1", "upload": 50, "download": 50, "metadata": {}, "chains": ["DIRECT"], "rule": "MATCH"}]}
    collector._process_snapshot(msg1, t1)
    collector._process_snapshot(msg2, t2)
    key1 = (_minute_ts(t1), "未知", "direct")
    key2 = (_minute_ts(t2), "未知", "direct")
    total_up = collector.minute_agg.get(key1, [0, 0])[0] + collector.minute_agg.get(key2, [0, 0])[0]
    assert total_up == 0


def test_minute_boundary(collector):
    msg1 = {"connections": [{"id": "1", "upload": 10, "download": 10, "metadata": {}, "chains": ["DIRECT"], "rule": "MATCH"}]}
    msg2 = {"connections": [{"id": "1", "upload": 20, "download": 20, "metadata": {}, "chains": ["DIRECT"], "rule": "MATCH"}]}
    collector._process_snapshot(msg1, 59.0)
    collector._process_snapshot(msg2, 61.0)
    assert (0, "未知", "direct") in collector.minute_agg
    assert (60, "未知", "direct") in collector.minute_agg


def test_connection_removed(collector):
    msg1 = {"connections": [{"id": "1", "upload": 0, "download": 0, "metadata": {}, "chains": ["DIRECT"], "rule": "MATCH"}]}
    msg2 = {"connections": []}
    collector._process_snapshot(msg1, 1000.0)
    assert "1" in collector.live_map
    collector._process_snapshot(msg2, 1010.0)
    assert "1" not in collector.live_map
