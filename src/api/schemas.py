from typing import Optional
from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    run_id: Optional[str] = None
    include_stale: bool = False


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    unverified: list = []
    status: str = "ok"


class DecisionRequest(BaseModel):
    by: str = "reviewer"
