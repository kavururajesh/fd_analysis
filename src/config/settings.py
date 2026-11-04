"""Central configuration. Variable names GIGACHAT_URL / GIGACHAT_CERT / GIGACHAT_KEY / GIGACHAT_CHAIN / CHAT_ENDPOINT
are the same as in the existing evaluation/config.py. Values come from environment variables or a `.env` file."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR, OUTPUT_DIR, LOG_DIR, CONFIG_DIR = ROOT / "data", ROOT / "output", ROOT / "logs", ROOT / "config"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if value[:1] in ("'", '"') and value[0] in value[1:]:        # quoted value: keep everything inside the quotes
                value = value[1:value.index(value[0], 1)]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()           # "local   # comment" -> "local"
            os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT / ".env")


def _env(name, default=""):
    return os.getenv(name, default)


def _bool(name, default):
    return _env(name, str(default)).lower() in ("1", "true", "yes", "on")


# ---------------- GigaChat (mutual TLS: client certificate + key, server chain) ----------------
_cert_dir = Path.home() / "GigaChatCertificates"
GIGACHAT_URL = _env("GIGACHAT_URL")                                     # e.g. https://<host>/v1
GIGACHAT_CERT = _env("GIGACHAT_CERT", str(_cert_dir / "dev.crt.txt"))
GIGACHAT_KEY = _env("GIGACHAT_KEY", str(_cert_dir / "dev.key"))
GIGACHAT_CHAIN = _env("GIGACHAT_CHAIN", str(_cert_dir / "chain_pem.txt"))
CHAT_ENDPOINT = _env("CHAT_ENDPOINT", "/chat/completions")
GIGACHAT_MODEL = _env("GIGACHAT_MODEL", "GigaChat")
LLM_MODE = _env("LLM_MODE", "auto")                                     # auto | gigachat | groq | openrouter | offline
# ---------------- OpenRouter (for testing outside the Sber network only; key comes from .env, never from code) ----------------
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
OPENROUTER_URL = _env("OPENROUTER_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = _env("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")
OPENROUTER_PROXY = _env("OPENROUTER_PROXY")                              # optional, e.g. http://proxy.company:8080
# ---------------- Groq (OpenAI-compatible; for testing outside the Sber network only) ----------------
GROQ_API_KEY = _env("GROQ_API_KEY")
GROQ_URL = _env("GROQ_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = _env("GROQ_MODEL", "openai/gpt-oss-120b")
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.05"))
LLM_TIMEOUT = int(_env("LLM_TIMEOUT", "120"))
LLM_RETRIES = int(_env("LLM_RETRIES", "3"))

# ---------------- Data sources & browser ----------------
SOURCE_MODE = _env("SOURCE_MODE", "local")                               # local = saved bank-page snapshots served on this machine | live = real bank sites
SOURCES_FILE = Path(_env("SOURCES_FILE", str(CONFIG_DIR / f"sources.{SOURCE_MODE}.yaml")))
BROWSER_CHANNEL = _env("BROWSER_CHANNEL", "msedge")                     # msedge | chrome | chromium (bundled)
BROWSER_HEADLESS = _bool("BROWSER_HEADLESS", True)
BROWSER_TIMEOUT_MS = int(_env("BROWSER_TIMEOUT_MS", "45000"))
BROWSER_PROXY = _env("BROWSER_PROXY")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
FIXTURE_PORT = int(_env("FIXTURE_PORT", "8765"))
FIXTURE_DELAY_MS = int(_env("FIXTURE_DELAY_MS", "0"))                  # testing aid: slow down the local bank pages to see the effect of parallel collection
FIXTURE_DIR = ROOT / "samples"                                         # local page snapshots + reference workbook (kept outside data/ so ignore rules for data/ cannot drop it)

# ---------------- Storage ----------------
DB_PATH = Path(_env("DB_PATH", str(DATA_DIR / "fd_agent.db")))
CURRENT_DIR = DATA_DIR / "current"                                       # the one live dataset (rates.csv + manifest + evidence)
STAGING_DIR = DATA_DIR / "staging"                                       # new data lives here until it is validated and promoted
KEEP_RUNS = int(_env("KEEP_RUNS", "60"))                                  # compact rate history (numbers only) kept for trend charts

# ---------------- Agent behaviour ----------------
SUPERVISOR_MAX_STEPS = int(_env("SUPERVISOR_MAX_STEPS", "30"))
COLLECTOR_MAX_STEPS = int(_env("COLLECTOR_MAX_STEPS", "10"))
COLLECT_WORKERS = int(_env("COLLECT_WORKERS", "3"))                       # sources read at the same time (1 = one by one); each worker runs its own browser
COLLECT_PER_HOST = int(_env("COLLECT_PER_HOST", "1"))                    # simultaneous requests allowed to the same website
COLLECT_LLM_LIMIT = int(_env("COLLECT_LLM_LIMIT", "2"))                  # simultaneous LLM calls during self-healing
COLLECT_RETRIES = int(_env("COLLECT_RETRIES", "1"))                      # extra attempts after a temporary network problem
COLLECT_TOTAL_DEADLINE_S = int(_env("COLLECT_TOTAL_DEADLINE_S", "900"))  # a hung source cannot block the run longer than this
ANALYST_MAX_STEPS = int(_env("ANALYST_MAX_STEPS", "8"))
AUTO_PUBLISH_CLEAN = _bool("AUTO_PUBLISH_CLEAN", True)                  # True = a clean, validated refresh replaces the live dataset automatically; flagged runs wait for a reviewer
MAX_RATE_MOVE_PP = float(_env("MAX_RATE_MOVE_PP", "1.0"))               # a bigger move vs the published rate needs human review

# ---------------- Finance domain ----------------
SBER = "Sberbank corporate"
NO_LIMIT, EPS = 1e9, 1e-9
STATUSES = ["current", "proxy", "default_table", "stale"]
DEFAULT_STATUSES = ["current", "proxy", "default_table"]
TENOR_GRID = [7, 14, 30, 45, 60, 75, 89, 90, 91, 120, 150, 180, 210, 240, 270, 365, 540, 730, 1095, 1825]
AMOUNT_GRID = [1, 3, 5, 10, 15, 25, 50, 75, 100, 150]                   # Rs crore
