"""Playwright wrapper. Tries the Edge/Chrome already installed on the laptop first (no download), then bundled Chromium.
One browser per refresh run, one isolated context per source. All Playwright calls must stay in ONE thread."""
from src.config import settings as S
from src.config.logging_config import get_logger

log = get_logger(__name__)


class BrowserUnavailable(RuntimeError):
    pass


class BrowserManager:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._contexts = []
        self.channel_used = None

    def _start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        opts = {"headless": S.BROWSER_HEADLESS}
        if S.BROWSER_PROXY:
            opts["proxy"] = {"server": S.BROWSER_PROXY}
        channels = ([S.BROWSER_CHANNEL] if S.BROWSER_CHANNEL not in ("", "chromium") else []) + [None]
        errors = []
        for channel in channels:
            try:
                self._browser = self._pw.chromium.launch(channel=channel, **opts) if channel else self._pw.chromium.launch(**opts)
                self.channel_used = channel or "chromium"
                log.info("Browser started: %s", self.channel_used)
                return
            except Exception as e:
                errors.append(f"{channel or 'bundled chromium'}: {str(e).splitlines()[0][:120]}")
        self._pw.stop()
        self._pw = None
        raise BrowserUnavailable("No browser could be started (" + "; ".join(errors) +
                                 "). Install Microsoft Edge or Chrome, or run: playwright install chromium")

    def new_page(self):
        if self._browser is None:
            self._start()
        ctx = self._browser.new_context(user_agent=S.USER_AGENT, viewport={"width": 1400, "height": 1000})
        ctx.set_default_timeout(S.BROWSER_TIMEOUT_MS)
        self._contexts.append(ctx)
        return ctx.new_page()

    def close(self):
        for ctx in self._contexts:
            try:
                ctx.close()
            except Exception:
                pass
        self._contexts = []
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = self._pw = None
