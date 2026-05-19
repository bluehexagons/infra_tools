"""Tests for lib/proxmox_placement.py.

Scoring is pure; these tests build :class:`NodeSnapshot` instances directly
and never touch SSH or argparse.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.proxmox_hosts import ProxmoxHost
from lib.proxmox_placement import (
    NodeSnapshot,
    PlacementRequest,
    is_hot,
    plan_placement,
    plan_rebalance,
    score_candidate,
)
from lib.proxmox_summary import NodeSummary


_GIB = 1024 ** 3


def _snap(
    *,
    name: str = "pve1",
    cpu_usage: float = 0.10,
    cpu_count: int = 8,
    memory_used: int = 4 * _GIB,
    memory_total: int = 16 * _GIB,
    disk_used: int = 50 * _GIB,
    disk_total: int = 500 * _GIB,
    guests_running: int = 2,
    guests_stopped: int = 0,
    tags: list[str] | None = None,
) -> NodeSnapshot:
    host = ProxmoxHost(name=name, address=f"10.0.0.{hash(name) % 250 + 1}")
    if tags:
        host.tags = list(tags)
    summary = NodeSummary(
        node_name=name,
        cpu_usage=cpu_usage,
        cpu_count=cpu_count,
        memory_used=memory_used,
        memory_total=memory_total,
        swap_used=0,
        swap_total=0,
        disk_used=disk_used,
        disk_total=disk_total,
        uptime_seconds=3600,
        guests_running=guests_running,
        guests_stopped=guests_stopped,
    )
    return NodeSnapshot(host=host, summary=summary)


class TestScoreCandidate(unittest.TestCase):
    def test_fits_when_request_is_within_budget(self) -> None:
        snap = _snap()
        cand = score_candidate(snap, PlacementRequest(cores=2, memory_mib=2048))
        self.assertTrue(cand.fits)
        self.assertGreater(cand.score, 0)

    def test_disqualified_on_insufficient_memory(self) -> None:
        snap = _snap(memory_used=15 * _GIB, memory_total=16 * _GIB)
        cand = score_candidate(snap, PlacementRequest(cores=1, memory_mib=4096))
        self.assertFalse(cand.fits)
        self.assertTrue(any("memory" in r for r in cand.reasons))

    def test_disqualified_on_core_count(self) -> None:
        snap = _snap(cpu_count=4)
        cand = score_candidate(snap, PlacementRequest(cores=16, memory_mib=512))
        self.assertFalse(cand.fits)
        self.assertTrue(any("cores" in r for r in cand.reasons))

    def test_disqualified_on_avoid_tag(self) -> None:
        snap = _snap(tags=["edge"])
        cand = score_candidate(
            snap,
            PlacementRequest(cores=1, memory_mib=512, avoid_tags=["edge"]),
        )
        self.assertFalse(cand.fits)

    def test_disqualified_on_excluded_node(self) -> None:
        snap = _snap(name="pve2")
        cand = score_candidate(
            snap,
            PlacementRequest(cores=1, memory_mib=512, exclude_nodes=["pve2"]),
        )
        self.assertFalse(cand.fits)

    def test_prefer_tag_boosts_score(self) -> None:
        plain = _snap(name="a")
        tagged = _snap(name="b", tags=["fast-ssd"])
        req = PlacementRequest(cores=1, memory_mib=512, prefer_tags=["fast-ssd"])
        plain_score = score_candidate(plain, req).score
        tagged_score = score_candidate(tagged, req).score
        self.assertGreater(tagged_score, plain_score)

    def test_emptier_node_outranks_loaded_node(self) -> None:
        empty = _snap(name="empty", cpu_usage=0.05, memory_used=2 * _GIB)
        loaded = _snap(name="loaded", cpu_usage=0.70, memory_used=12 * _GIB)
        req = PlacementRequest(cores=2, memory_mib=2048)
        self.assertGreater(
            score_candidate(empty, req).score,
            score_candidate(loaded, req).score,
        )


class TestPlanPlacement(unittest.TestCase):
    def test_ranks_fitting_nodes_first(self) -> None:
        snaps = [
            _snap(name="full", memory_used=15 * _GIB, memory_total=16 * _GIB),
            _snap(name="ok", memory_used=2 * _GIB, memory_total=16 * _GIB),
            _snap(name="medium", memory_used=8 * _GIB, memory_total=16 * _GIB),
        ]
        plan = plan_placement(snaps, PlacementRequest(cores=1, memory_mib=4096))
        # First two fit, last one is the full node.
        self.assertTrue(plan.candidates[0].fits)
        self.assertEqual(plan.candidates[0].host_name, "ok")
        self.assertFalse(plan.candidates[-1].fits)
        self.assertEqual(plan.candidates[-1].host_name, "full")


class TestRebalance(unittest.TestCase):
    def test_is_hot_thresholds(self) -> None:
        self.assertFalse(is_hot(_snap(cpu_usage=0.50).summary))
        self.assertTrue(is_hot(_snap(cpu_usage=0.95).summary))
        self.assertTrue(
            is_hot(_snap(memory_used=15 * _GIB, memory_total=16 * _GIB).summary)
        )

    def test_plan_rebalance_skips_cold_nodes(self) -> None:
        snaps = [
            _snap(name="cold", cpu_usage=0.10, memory_used=2 * _GIB),
            _snap(name="cool", cpu_usage=0.20, memory_used=4 * _GIB),
        ]
        self.assertEqual(plan_rebalance(snaps, {}), [])

    def test_plan_rebalance_excludes_self_from_destinations(self) -> None:
        snaps = [
            _snap(name="hot", cpu_usage=0.95, memory_used=10 * _GIB),
            _snap(name="cool", cpu_usage=0.10, memory_used=2 * _GIB),
        ]
        result = plan_rebalance(snaps, {"hot": ["100 vm  running web"]})
        self.assertEqual(len(result), 1)
        sug = result[0]
        self.assertEqual(sug.hot_host, "hot")
        self.assertEqual([c.host_name for c in sug.destinations], ["cool"])
        self.assertEqual(sug.guests, ["100 vm  running web"])


if __name__ == "__main__":
    unittest.main()
