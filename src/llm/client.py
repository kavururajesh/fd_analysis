"""GigaChat client - same call style as evaluation/gigachat_client.py: plain `requests` POST to GIGACHAT_URL + CHAT_ENDPOINT,
mutual TLS via cert=(GIGACHAT_CERT, GIGACHAT_KEY) and verify=GIGACHAT_CHAIN.
Added: multi-turn `chat()` (agents need history), retries with back-off, clear errors."""
import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

from src.config import settings as S
from src.config.logging_config import get_logger
from src.prompts.system_prompts import get_system_prompt

log = get_logger(__name__)


class LLMError(Exception):
    """Any failure to get an answer from the LLM (config, network, HTTP, bad response)."""


class GigaChatClient:
    is_offline = False
    name = "GigaChat"

    def __init__(self, base_url=None, cert=None, key=None, chain=None, endpoint=None, timeout=None, retries=None):
        self.base_url = base_url or S.GIGACHAT_URL
        self.chat_endpoint = endpoint or S.CHAT_ENDPOINT
        self.cert = (cert or S.GIGACHAT_CERT, key or S.GIGACHAT_KEY)
        self.verify = chain or S.GIGACHAT_CHAIN
        self.timeout = timeout or S.LLM_TIMEOUT
        self.retries = retries or S.LLM_RETRIES

    # ---------- configuration check ----------
    def problems(self) -> List[str]:
        out = []
        if not self.base_url:
            out.append("GIGACHAT_URL is not set")
        for label, path in (("GIGACHAT_CERT", self.cert[0]), ("GIGACHAT_KEY", self.cert[1]), ("GIGACHAT_CHAIN", self.verify)):
            if not path or not os.path.exists(path):
                out.append(f"{label} file not found: {path}")
        return out

    # ---------- same interface as the existing client ----------
    def generate_response(self, user_content: str, task: str = "default", context: str = "", model: Optional[str] = None,
                          temperature: Optional[float] = None, n: int = 1) -> Dict[str, Any]:
        """Generate response using GigaChat API (raw API json, like the existing client)."""
        content = f"{context}\n\n{user_content}" if context else user_content
        messages = [{"role": "system", "content": get_system_prompt(task)}, {"role": "user", "content": content}]
        return self._post(messages, model, temperature, n)

    def extract_generated_text(self, api_response: Dict[str, Any]) -> str:
        try:
            if "choices" in api_response and len(api_response["choices"]) > 0:
                return api_response["choices"][0].get("message", {}).get("content", "")
            return ""
        except (KeyError, IndexError, AttributeError) as e:
            raise LLMError(f"Failed to extract text from API response: {str(e)}")

    # ---------- used by the agents ----------
    def chat(self, messages: List[Dict[str, str]], task: Optional[str] = None, temperature: Optional[float] = None,
             model: Optional[str] = None, n: int = 1) -> str:
        """Multi-turn chat -> text. `task` is accepted for interface compatibility (only the mock uses it)."""
        return self.extract_generated_text(self._post(messages, model, temperature, n))

    # ---------- transport ----------
    def _post(self, messages, model, temperature, n) -> Dict[str, Any]:
        issues = self.problems()
        if issues:
            raise LLMError("GigaChat is not configured: " + "; ".join(issues))
        payload = json.dumps({
            "model": model or S.GIGACHAT_MODEL,
            "messages": messages,
            "n": n,
            "temperature": S.LLM_TEMPERATURE if temperature is None else temperature,
        })
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.request("POST", self.base_url + self.chat_endpoint, headers=headers, data=payload,
                                            cert=self.cert, verify=self.verify, timeout=self.timeout)
                if response.status_code == 200:
                    return response.json()
                last = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
            except (requests.ConnectionError, requests.Timeout) as e:
                last = f"{type(e).__name__}: {e}"
            except (requests.RequestException, ValueError) as e:
                last = f"{type(e).__name__}: {e}"
                break
            log.warning("GigaChat attempt %d/%d failed: %s", attempt, self.retries, last)
            time.sleep(min(2 ** attempt, 8))
        raise LLMError(f"GigaChat request failed: {last}")
