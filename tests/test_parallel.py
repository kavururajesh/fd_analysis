"""Parallel collection: correctness, politeness, isolation, retries, timeout, and identical output to the sequential run."""
import threading
import time

import pytest

from src.agent.collector import CollectResult
from src.agent.parallel import ParallelCollector
from src.agent.state import Trace
from src.agent.supervisor import Supervisor
from src.llm.offline import OfflineLLM
from src.tools.sources import SourceConfig, load_sources


def src(i, host="a.example"):
    return SourceConfig(id=f"s{i}", bank=f"B{i}", product="p", status="current", kind="html", url=f"https://{host}/{i}")


class FakeAgent:
    """Stands in for the collector: records how many ran at once and which hosts overlapped."""
    def __init__(self, state, delay=0.15, fail=(), flaky=()):
        self.st, self.delay, self.fail, self.flaky = state, delay, set(fail), set(flaky)

    def collect(self, source, run_id, prev=None):
        with self.st["lock"]:
            self.st["now"] += 1; self.st["peak"] = max(self.st["peak"], self.st["now"])
            host = source.url.split("/")[2]; self.st["host_now"][host] = self.st["host_now"].get(host, 0) + 1
            self.st["host_peak"][host] = max(self.st["host_peak"].get(host, 0), self.st["host_now"][host])
            self.st["calls"][source.id] = self.st["calls"].get(source.id, 0) + 1
            n = self.st["calls"][source.id]
        try:
            time.sleep(self.delay)
            if source.id in self.fail:
                raise RuntimeError("boom")
            if source.id in self.flaky and n == 1:
                return CollectResult(source.id, False, "failed", errors=["net::ERR_CONNECTION_RESET"])
            return CollectResult(source.id, True, "spec_yaml")
        finally:
            with self.st["lock"]:
                self.st["now"] -= 1; self.st["host_now"][host] -= 1


def make(workers=4, per_host=1, **agent_kw):
    st = dict(lock=threading.Lock(), now=0, peak=0, host_now={}, host_peak={}, calls={})
    pc = ParallelCollector(OfflineLLM(), None, Trace("t"), "x", workers=workers, per_host=per_host, retries=1,
                           agent_factory=lambda b: FakeAgent(st, **agent_kw))
    return pc, st


def test_runs_in_parallel_and_returns_every_source():
    pc, st = make(workers=4)
    srcs = [src(i, host=f"h{i}.example") for i in range(8)]
    t0 = time.time(); res = pc.collect(srcs, "r", None); took = time.time() - t0
    assert set(res) == {s.id for s in srcs} and all(r.ok for r in res.values())
    assert 2 <= st["peak"] <= 4                       # really parallel, never more than the worker count
    assert took < 8 * 0.15 * 0.7                      # clearly faster than one by one


def test_one_site_is_never_hit_twice_at_the_same_time():
    pc, st = make(workers=4, per_host=1)
    res = pc.collect([src(i, host="same.example") for i in range(4)] + [src(9, host="other.example")], "r", None)
    assert len(res) == 5 and st["host_peak"]["same.example"] == 1


def test_a_crash_in_one_source_does_not_stop_the_others():
    pc, _ = make(workers=3, fail={"s2"})
    res = pc.collect([src(i, host=f"h{i}") for i in range(5)], "r", None)
    assert not res["s2"].ok and "boom" in res["s2"].errors[0]
    assert all(res[k].ok for k in ("s0", "s1", "s3", "s4"))


def test_temporary_network_errors_are_retried_once():
    pc, st = make(workers=2, flaky={"s1"})
    res = pc.collect([src(0, "a"), src(1, "b")], "r", None)
    assert res["s1"].ok and res["s1"].metrics["attempts"] == 2 and st["calls"]["s1"] == 2


def test_hung_source_times_out_instead_of_blocking_the_run():
    pc, _ = make(workers=2, delay=3)
    pc.deadline = 1
    t0 = time.time(); res = pc.collect([src(0, "a"), src(1, "b")], "r", None)
    assert time.time() - t0 < 2.5 and all(not r.ok and "timed out" in r.errors[0] for r in res.values())


def test_single_worker_runs_inline_in_the_calling_thread():
    seen = []
    pc = ParallelCollector(OfflineLLM(), None, Trace("t"), "x", workers=1, agent_factory=lambda b: type("A", (), {"collect": lambda self, s, r, p=None: (seen.append(threading.current_thread().name), CollectResult(s.id, True, "x"))[1]})())
    pc.collect([src(0), src(1)], "r", None)
    assert seen == [threading.current_thread().name] * 2


def test_parallel_and_sequential_runs_produce_the_same_dataset(store, browser, fixture_site, files, tmp_path):
    """Real browsers against the local pages: the order sources finish in must not change the data."""
    from src.datastore.files import DatasetFiles
    from src.memory.store import Store
    seq = Supervisor(OfflineLLM(), store, browser, Trace("a", store), files, workers=1).run("a", load_sources(), "local")
    store2 = Store(tmp_path / "b.db"); files2 = DatasetFiles(tmp_path / "cur2", tmp_path / "stg2")
    par = Supervisor(OfflineLLM(), store2, browser, Trace("b", store2), files2, workers=3).run("b", load_sources(), "local")
    cols = ["source_id", "amt_label", "tenor_label", "rate"]
    a = seq.df.sort_values(cols).reset_index(drop=True)[cols]; b = par.df.sort_values(cols).reset_index(drop=True)[cols]
    assert a.equals(b) and len(a) > 500
    assert list(seq.df.source_id.unique()) == list(par.df.source_id.unique())       # same order: config order, not finish order
    assert all(r.metrics.get("seconds") is not None for r in par.results.values())


def test_probe_opens_every_source_in_parallel(browser, fixture_site, store):
    from src.tools.browser import BrowserManager
    pc = ParallelCollector(OfflineLLM(), store, Trace("p"), "x", workers=3, per_host=9, browser_factory=BrowserManager)
    srcs = load_sources()
    out = pc.probe(srcs, browser=browser)
    assert set(out) == {s.id for s in srcs} and all(r["ok"] and r["tables"] >= 1 for r in out.values())


def test_live_config_is_wide_and_well_formed():
    from src.config import settings as S
    live = load_sources(S.CONFIG_DIR / "sources.live.yaml")
    assert len({s.bank for s in live}) >= 25 and len({s.id for s in live}) == len(live)
    assert all(s.url.startswith("https://") and s.kind in ("browser", "pdf", "html") for s in live)
