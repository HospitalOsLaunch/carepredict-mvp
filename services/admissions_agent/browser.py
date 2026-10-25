"""A sandboxed browser page for the agent.

Every request to a host outside the allowlist is aborted at the network level, so
neither a playbook mistake nor a model following an injected instruction on a page can
send data elsewhere. Model engines act through ``click``/``type``/``key``/``scroll`` in
screenshot pixel space; playbooks act through CSS selectors.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route, sync_playwright


class BlockedNavigation(RuntimeError):
    pass


@dataclass(frozen=True)
class Screenshot:
    png: bytes
    width: int
    height: int


# Keys a model may press. Browser-level shortcuts (address bar, new tab, devtools,
# downloads) are refused: the page is the only surface the agent works on.
ALLOWED_KEYS = {
    "Return",
    "Enter",
    "Tab",
    "Escape",
    "BackSpace",
    "Backspace",
    "Delete",
    "space",
    "Up",
    "Down",
    "Left",
    "Right",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Home",
    "End",
    "Page_Up",
    "Page_Down",
    "PageUp",
    "PageDown",
    "shift+Tab",
    "ctrl+a",
}
KEY_ALIASES = {
    "Return": "Enter",
    "BackSpace": "Backspace",
    "Page_Up": "PageUp",
    "Page_Down": "PageDown",
    "Up": "ArrowUp",
    "Down": "ArrowDown",
    "Left": "ArrowLeft",
    "Right": "ArrowRight",
    "space": " ",
    "shift+Tab": "Shift+Tab",
    "ctrl+a": "Control+a",
}


class BrowserSession:
    def __init__(
        self,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        viewport: tuple[int, int] = (1280, 800),
        headless: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.allowed_hosts = set(allowed_hosts)
        self.viewport = viewport
        self._pw: Playwright = sync_playwright().start()
        self._browser: Browser = self._pw.chromium.launch(headless=headless)
        self._context: BrowserContext = self._browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            accept_downloads=False,
        )
        self._context.route("**/*", self._guard)
        self.page: Page = self._context.new_page()
        self.blocked: list[str] = []

    def _guard(self, route: Route) -> None:
        url = route.request.url
        host = urlparse(url).hostname or ""
        if url.startswith(("data:", "blob:")) or host in self.allowed_hosts:
            route.continue_()
        else:
            self.blocked.append(url)
            route.abort("blockedbyclient")

    # --- navigation shared by all engines -----------------------------------------

    def goto(self, path_or_url: str) -> None:
        url = (
            urljoin(self.base_url + "/", path_or_url.lstrip("/"))
            if "://" not in path_or_url
            else path_or_url
        )
        host = urlparse(url).hostname or ""
        if host not in self.allowed_hosts:
            raise BlockedNavigation(f"hôte non autorisé : {host}")
        self.page.goto(url, wait_until="domcontentloaded")

    def screenshot(self) -> Screenshot:
        png = self.page.screenshot(type="png")
        return Screenshot(png, self.viewport[0], self.viewport[1])

    # --- pixel-space actions for model engines ------------------------------------

    def _inside(self, x: float, y: float) -> tuple[float, float]:
        w, h = self.viewport
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"coordonnées hors écran : ({x:.0f}, {y:.0f})")
        return x, y

    def click(self, x: float, y: float, button: str = "left", count: int = 1) -> None:
        x, y = self._inside(x, y)
        self.page.mouse.click(x, y, button=button, click_count=count)  # type: ignore[arg-type]
        self._settle()

    def move(self, x: float, y: float) -> None:
        x, y = self._inside(x, y)
        self.page.mouse.move(x, y)

    def type_text(self, text: str) -> None:
        if len(text) > 4000:
            raise ValueError("texte trop long")
        self.page.keyboard.type(text)

    def key(self, combo: str, repeat: int = 1) -> None:
        if combo not in ALLOWED_KEYS:
            raise ValueError(f"touche non autorisée : {combo}")
        for _ in range(max(1, min(repeat, 20))):
            self.page.keyboard.press(KEY_ALIASES.get(combo, combo))
        self._settle()

    def scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        x, y = self._inside(x, y)
        self.page.mouse.move(x, y)
        self.page.mouse.wheel(dx, dy)

    def _settle(self) -> None:
        # A click that does not navigate simply times out here, which is fine.
        with contextlib.suppress(Exception):
            self.page.wait_for_load_state("domcontentloaded", timeout=5000)

    def close(self) -> None:
        try:
            self._context.close()
            self._browser.close()
        finally:
            self._pw.stop()

    def __enter__(self) -> BrowserSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
