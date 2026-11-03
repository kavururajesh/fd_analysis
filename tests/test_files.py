"""Safe replacement of datasets: old files are deleted only after the new ones are verified and live."""
import pandas as pd
import pytest

from src.agent.state import Trace
from src.agent.supervisor import Supervisor
from src.data.files import PromotionError
from src.llm.offline import OfflineLLM
from src.service import FDService
from src.tools.sources import load_sources


def run(store, browser, files, rid):
    return Supervisor(OfflineLLM(), store, browser, Trace(rid, store), files).run(rid, load_sources(), "local")


def test_first_run_waits_then_clean_runs_replace_automatically(store, browser, fixture_site, files):
    ctx1 = run(store, browser, files, "r1")
    assert ctx1.status == "pending_review" and files.load_current() == (None, None)       # nothing live before approval
    FDService(store, OfflineLLM(), files).approve("r1")
    assert files.manifest()["run_id"] == "r1" and not (files.staging / "r1").exists()
    old_files = {p.name for p in (files.current / "evidence").iterdir()}
    assert old_files                                                                          # evidence moved with the dataset
    ctx2 = run(store, browser, files, "r2")                                                  # same data, same layouts -> clean
    assert ctx2.status == "published"                                                        # replaced without human work
    assert files.manifest()["run_id"] == "r2"
    assert not (files.current.with_name("current.old")).exists()                             # old copy removed after the swap
    assert list(files.staging.iterdir()) == []                                               # no leftovers
    rid, df = files.load_current()
    assert rid == "r2" and len(df) == len(ctx2.df)


def test_failed_promotion_keeps_previous_data(store, browser, fixture_site, files):
    run(store, browser, files, "r1")
    svc = FDService(store, OfflineLLM(), files)
    svc.approve("r1")
    before = files.manifest()["sha256"]
    run(store, browser, files, "r2")                                                         # auto-published
    ctx3 = Supervisor(OfflineLLM(), store, browser, Trace("r3", store), files)
    # corrupt the staged file of a new run after it was written: promotion must refuse and r2 stays live
    r3 = ctx3.run("r3", load_sources(), "local")
    assert r3.status == "published"
    run_id = "r4"
    store.save_run(run_id, "pending_review", "local", files.load_current()[1], [], [], {}, "")
    files.stage(run_id, files.load_current()[1], {})
    (files.staging / run_id / "rates.csv").write_text("tampered")
    live_before = files.manifest()["run_id"]
    with pytest.raises(ValueError):
        svc.approve(run_id)
    assert files.manifest()["run_id"] == live_before and files.load_current()[1] is not None
    assert store.get_run(run_id)["status"] == "pending_review"


def test_old_pending_runs_become_superseded(store, browser, fixture_site, files):
    run(store, browser, files, "r1")                                                         # pending (first run)
    run(store, browser, files, "r2")                                                         # also pending (no baseline yet)
    svc = FDService(store, OfflineLLM(), files)
    svc.approve("r2")
    assert store.get_run("r1")["status"] == "superseded"
    with pytest.raises(ValueError):
        svc.approve("r1")


def test_verify_detects_bad_staging(files):
    from src.domain.schema import COLUMNS
    df = pd.DataFrame(columns=COLUMNS)
    files.stage("x", df, {})
    with pytest.raises(PromotionError):
        files.promote("x")                                                                   # empty dataset fails validation
    with pytest.raises(PromotionError):
        files.promote("missing")
