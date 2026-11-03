"""Pick the LLM: real GigaChat if configured, otherwise the offline rule-based engine."""
from src.config import settings as S
from src.llm.client import GigaChatClient
from src.llm.offline import OfflineLLM


def get_llm(mode=None):
    mode = (mode or S.LLM_MODE).lower()
    if mode == "offline":
        return OfflineLLM()
    client = GigaChatClient()
    if mode == "gigachat":
        return client
    return client if not client.problems() else OfflineLLM()          # auto


def llm_status(llm):
    if llm.is_offline:
        return "Rule-based engine (GigaChat not connected)"
    return "GigaChat"
