"""Publisher: the only place where a run becomes the live dataset (files first, database status second)."""
from src.data.files import DatasetFiles, PromotionError
from src.memory.store import Store


class Publisher:
    def __init__(self, store: Store, files: DatasetFiles):
        self.store, self.files = store, files

    def stage(self, run_id, df, meta):
        if df is not None and len(df):
            self.files.stage(run_id, df, meta)

    def publish(self, run_id: str, by: str = "system"):
        """Verify + swap the files, then mark the run published. If the file swap fails nothing changes (old data stays live)."""
        info = self.files.promote(run_id)
        self.store.approve_specs(run_id)                     # layouts the agent proposed become trusted
        self.store.set_status(run_id, "published", by)
        self.store.supersede_pending(run_id)
        return info
