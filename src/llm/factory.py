"""Pick the LLM. Order in auto mode: GigaChat if configured, else OpenRouter if a key is set, else offline rules."""
from src.config import settings as S
from src.llm.client import GigaChatClient, GroqClient, OpenRouterClient
from src.llm.offline import OfflineLLM


def get_llm(mode=None):
    mode = (mode or S.LLM_MODE).lower()
    if mode == "offline":
        return OfflineLLM()
    if mode == "groq":
        return GroqClient()
    if mode == "openrouter":
        return OpenRouterClient()
    giga = GigaChatClient()
    if mode == "gigachat":
        return giga
    if not giga.problems():                                           # auto
        return giga
    for test_client in (GroqClient(), OpenRouterClient()):
        if not test_client.problems():
            return test_client
    return OfflineLLM()


def llm_status(llm):
    if llm.is_offline:
        return "Rule-based engine (no LLM connected)"
    if getattr(llm, "name", "") in ("OpenRouter", "Groq"):
        return f"{llm.name} ({llm.model})"
    return "GigaChat"
