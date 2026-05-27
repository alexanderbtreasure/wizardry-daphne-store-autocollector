"""
Wizardry Variants Daphne — JP webstore (webstore.wizardry.info) free-item autocollector.

Unlike the international store (store.wizardry.info), the JP webstore geo-restricts the
redeem action: clicking 受け取る from a non-Japan IP returns error code 70003
("お住まいの地域では、本サービスをご利用いただけません"). The login step is NOT
geo-restricted, but the redeem is — so this script must run from a Japan IP
(e.g. an Oracle Cloud Tokyo/Osaka VM).

Auth: logs in fresh each run with email + password. LINE/OAuth login is not automatable.

It logs in once, then walks FREE_PRODUCT_IDS, claiming any item with stock remaining and
skipping those already claimed (残り：0). The weekly reward recurs; the first-time bonus
self-skips after its single claim, so it's harmless to leave in the list.

Credentials come from environment variables:
    WIZARDRY_JP_EMAIL
    WIZARDRY_JP_PASSWORD

Optional, for research/testing from a non-JP host via a Japan proxy (NOT set on the VM,
which already has a native Japan IP):
    WIZARDRY_JP_PROXY   e.g. socks5://127.0.0.1:1080  (an SSH `-D` tunnel through the VM)

Exit codes:
    0  all available items claimed (or already claimed) — nothing left to do
    1  at least one item was region-blocked (error 70003) — not running from a Japan IP
    2  login failed / missing credentials
    3  unexpected error (element not found, timeout, etc.)

Set WIZARDRY_JP_DEBUG=1 to write a Playwright trace (artifacts/trace_jp.zip)
and step screenshots to ./artifacts/ for debugging. View the trace with:
playwright show-trace artifacts/trace_jp.zip

Memory note: tuned for a 1 GB VM. Launches the headless-shell Chromium with lean flags.
Add swap on the VM (a 2 GB swapfile) before relying on this — Chromium can spike past 1 GB.
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Error as PWError,
    Page,
    sync_playwright,
    TimeoutError as PWTimeout,
)

BASE_URL = "https://webstore.wizardry.info"

# Free items to claim each run. The script claims any with stock and skips the rest,
# so order doesn't matter and already-claimed items are harmless.
FREE_PRODUCT_IDS = [
    "VvQwG2KoMz82",  # weekly recurring free reward — the primary cron target
    "D6Vj2rYxMjne",  # first-time-only bonus (オルグの貴石800個) — self-skips after one claim
]

ARTIFACT_DIR = Path(__file__).parent / "artifacts"

# Lean flags for a memory-constrained server with no display.
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]

# Region-block markers seen in the page when running from a non-JP IP.
BLOCK_MARKERS = ("70003", "ご利用いただけません", "ご利用が制限")

# Labels a post-受け取る confirmation dialog might use (if any).
CONFIRM_LABELS = ("受け取る", "確定", "確認", "はい", "OK")
ASSET_TYPES = {"font", "image", "media"}
DEBUG = os.environ.get("WIZARDRY_JP_DEBUG") == "1"
BLOCK_ASSETS = os.environ.get("WIZARDRY_JP_BLOCK_ASSETS") == "1"
LOGIN_WAIT_MS = int(os.environ.get("WIZARDRY_LOGIN_WAIT_MS", "20000"))
BLANK_WAIT_MS = int(os.environ.get("WIZARDRY_BLANK_WAIT_MS", "3000"))
HOLD_SECONDS = int(os.environ.get("WIZARDRY_HOLD_SECONDS", "0"))
PRODUCT_RECOVERY_ATTEMPTS = int(os.environ.get("WIZARDRY_PRODUCT_RECOVERY_ATTEMPTS", "4"))
PRODUCT_NAV_ATTEMPTS = int(os.environ.get("WIZARDRY_PRODUCT_NAV_ATTEMPTS", "3"))


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def compact(text: str, limit: int = 1200) -> str:
    text = " ".join(text.split())
    return text[-limit:]


def shot(page: Page, name: str) -> None:
    """Best-effort screenshot; never let screenshotting break the flow."""
    if not DEBUG:
        return
    try:
        page.screenshot(path=str(ARTIFACT_DIR / name))
    except Exception as e:  # noqa: BLE001
        log(f"(could not screenshot {name}: {e})")


def is_blocked(text: str) -> bool:
    return any(marker in text for marker in BLOCK_MARKERS)


def block_heavy_assets(context: BrowserContext) -> None:
    """Avoid loading assets that are not needed for text/button automation."""
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ASSET_TYPES
        else route.continue_(),
    )


def dismiss_cookie_consent(page: Page) -> None:
    """Dismiss the consent layer if this is a fresh browser profile."""
    selectors = (
        "#CybotCookiebotDialogBodyButtonDecline",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll",
        "button:visible:has-text('拒否')",
        "button:visible:has-text('全て許可')",
    )
    logged = False
    for _ in range(12):
        for selector in selectors:
            button = page.locator(selector)
            try:
                if button.count() > 0 and button.first.is_visible(timeout=500):
                    if not logged:
                        log("Dismissing cookie consent...")
                        logged = True
                    button.first.click(timeout=3000, force=True)
                    if wait_cookie_hidden(page):
                        return
            except Exception:  # noqa: BLE001
                continue
        page.wait_for_timeout(500)
    if logged:
        log("Cookie consent did not fully disappear; continuing.")


def wait_cookie_hidden(page: Page) -> bool:
    try:
        page.locator("#CybotCookiebotDialog").wait_for(state="hidden", timeout=3000)
        return True
    except PWTimeout:
        return False


def settle(page: Page, label: str) -> None:
    """Wait briefly after an action, but do not fail on long-polling/SPA traffic."""
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        log(f"Timed out waiting for {label} network idle; continuing.")


def signed_in_visible(page: Page, timeout: int = 15000) -> bool:
    try:
        page.get_by_role("button", name="マイページ").wait_for(
            state="visible", timeout=timeout
        )
        return True
    except PWTimeout:
        try:
            body = page.inner_text("body", timeout=1000)
            return "ゲームユーザーID" in body or "マイページ" in body
        except Exception:  # noqa: BLE001
            return False


def recover_blank_login(page: Page) -> bool:
    log("Login landed on about:blank; checking session state...")
    for candidate in page.context.pages:
        if candidate.url != "about:blank" and signed_in_visible(candidate, timeout=3000):
            log(f"Signed-in header detected on existing page: {candidate.url}")
            return True

    for action, label, attempts in (
        (
            lambda: page.goto(
                f"{BASE_URL}/product", wait_until="domcontentloaded", timeout=30000
            ),
            "opening product page",
            PRODUCT_RECOVERY_ATTEMPTS,
        ),
        (lambda: page.go_back(wait_until="domcontentloaded", timeout=15000), "going back", 1),
    ):
        try:
            for attempt in range(1, attempts + 1):
                log(f"Trying blank-page recovery by {label} ({attempt}/{attempts})...")
                action()
                if signed_in_visible(page, timeout=15000):
                    log(f"Signed-in header detected after {label}.")
                    return True
                page.wait_for_timeout(3000)
        except PWTimeout:
            log(f"Timed out while {label}.")
    return False


def visible_receive_button(page: Page):
    return page.locator("button:visible").filter(has_text="受け取る")


def enabled_receive_button(page: Page):
    return page.locator("button:visible:enabled").filter(has_text="受け取る")


def wait_for_claim_surface(page: Page, product_id: str) -> str:
    """Wait until the product modal/page is ready enough to decide what to do."""
    saw_disabled_receive = False
    for _ in range(30):
        body = page.inner_text("body")
        if "残り：0" in body:
            return "already"
        if enabled_receive_button(page).count() > 0:
            return "ready"
        receive = visible_receive_button(page)
        if receive.count() > 0:
            saw_disabled_receive = True
        if is_blocked(body):
            return "blocked"
        page.wait_for_timeout(1000)

    if saw_disabled_receive:
        log(f"[{product_id}] 受け取る button stayed disabled. Skipping.")
        return "already"

    log(f"[{product_id}] Timed out waiting for product claim modal/button.")
    try:
        log(f"[{product_id}] Page text tail: {compact(page.inner_text('body'))}")
    except Exception as e:  # noqa: BLE001
        log(f"[{product_id}] Could not read product page text: {e}")
    return "no_button"


def goto_product(page: Page, product_id: str) -> bool:
    url = f"{BASE_URL}/product/{product_id}"
    for attempt in range(1, PRODUCT_NAV_ATTEMPTS + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return True
        except PWError as e:
            if "about:blank" not in str(e):
                raise
            log(
                f"[{product_id}] Product navigation interrupted by about:blank; "
                f"retrying ({attempt}/{PRODUCT_NAV_ATTEMPTS})."
            )
            page.wait_for_timeout(2000)
    return False


def login(page: Page, email: str, password: str) -> bool:
    """Log in via the email+password form. Returns True on apparent success."""
    log("Opening login page...")
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    dismiss_cookie_consent(page)

    log("Choosing email login...")
    email_login = page.get_by_role("button", name="メールアドレスでログイン")
    try:
        email_login.click(timeout=15000)
    except PWTimeout:
        dismiss_cookie_consent(page)
        email_login.click(timeout=15000)

    log("Filling credentials...")
    page.locator("input[name='email']").fill(email)
    page.locator("input[name='password']").fill(password)

    log("Submitting login...")
    page.locator("form").get_by_role("button", name="ログイン").click(timeout=15000)
    deadline = time.monotonic() + LOGIN_WAIT_MS / 1000
    while time.monotonic() < deadline:
        if signed_in_visible(page, timeout=1000):
            return True
        if page.url == "about:blank":
            page.wait_for_timeout(BLANK_WAIT_MS)
            if recover_blank_login(page):
                return True
            break
        page.wait_for_timeout(1000)

    log(f"Login did not reach the signed-in header within {LOGIN_WAIT_MS // 1000} seconds.")
    log(f"Current URL: {page.url}")
    try:
        log(f"Visible page text tail: {compact(page.inner_text('body'))}")
    except Exception as e:  # noqa: BLE001
        log(f"Could not read page text after login failure: {e}")
    shot(page, "login_failed.png")
    return False


def claim_one(page: Page, product_id: str, idx: int) -> str:
    """
    Attempt to claim a single free product.
    Returns one of: "claimed", "already", "blocked", "no_button".
    """
    log(f"[{product_id}] Opening product page...")
    if not goto_product(page, product_id):
        log(f"[{product_id}] Could not open product page after retries.")
        return "no_button"
    state = wait_for_claim_surface(page, product_id)
    shot(page, f"{idx:02d}_product_{product_id}.png")

    if state == "already":
        log(f"[{product_id}] Already claimed this period (残り：0). Skipping.")
        return "already"
    if state == "blocked":
        log(f"[{product_id}] BLOCKED: region restriction (error 70003).")
        return "blocked"
    if state == "no_button":
        shot(page, f"{idx:02d}_no_button_{product_id}.png")
        return "no_button"

    body = page.inner_text("body")
    if "残り：0" in body:
        log(f"[{product_id}] Already claimed this period (残り：0). Skipping.")
        return "already"

    receive = enabled_receive_button(page)
    if receive.count() == 0:
        log(f"[{product_id}] No 受け取る button found.")
        return "no_button"

    log(f"[{product_id}] Clicking 受け取る...")
    receive.first.click()
    settle(page, f"{product_id} receive")
    shot(page, f"{idx:02d}_after_receive_{product_id}.png")

    body = page.inner_text("body")
    if is_blocked(body):
        log(f"[{product_id}] BLOCKED: region restriction (error 70003).")
        shot(page, f"{idx:02d}_BLOCKED_{product_id}.png")
        return "blocked"

    # Optional confirmation dialog.
    dialog = page.get_by_role("dialog")
    if dialog.count() > 0:
        for label in CONFIRM_LABELS:
            btn = dialog.get_by_role("button", name=label)
            if btn.count() > 0 and btn.first.is_enabled():
                log(f"[{product_id}] Confirmation dialog; clicking '{label}'...")
                btn.first.click()
                settle(page, f"{product_id} confirm")
                shot(page, f"{idx:02d}_after_confirm_{product_id}.png")
                break

    body = page.inner_text("body")
    if is_blocked(body):
        log(f"[{product_id}] BLOCKED: region restriction (error 70003) after confirm.")
        shot(page, f"{idx:02d}_BLOCKED_{product_id}.png")
        return "blocked"

    log(f"[{product_id}] Claimed (no region error).")
    return "claimed"


def run_flow(page: Page, email: str, password: str) -> int:
    if not login(page, email, password):
        return 2

    results = {}
    for i, pid in enumerate(FREE_PRODUCT_IDS, start=2):  # 01_* is the login screenshot
        try:
            results[pid] = claim_one(page, pid, i)
        except PWTimeout as e:
            log(f"[{pid}] timeout: {e}")
            results[pid] = "error"
        except Exception as e:  # noqa: BLE001
            log(f"[{pid}] unexpected: {e!r}")
            results[pid] = "error"

    log(f"Summary: {results}")

    if any(v == "blocked" for v in results.values()):
        return 1
    if any(v == "error" for v in results.values()):
        return 3
    return 0  # everything claimed or already claimed


def main() -> int:
    email = os.environ.get("WIZARDRY_JP_EMAIL")
    password = os.environ.get("WIZARDRY_JP_PASSWORD")
    if not email or not password:
        log("ERROR: set WIZARDRY_JP_EMAIL and WIZARDRY_JP_PASSWORD environment variables.")
        return 2

    if DEBUG:
        ARTIFACT_DIR.mkdir(exist_ok=True)

    headless = os.environ.get("WIZARDRY_HEADLESS", "1") != "0"
    launch_kwargs = {"headless": headless, "args": CHROMIUM_ARGS}
    slow_mo = os.environ.get("WIZARDRY_SLOW_MO_MS")
    if slow_mo:
        launch_kwargs["slow_mo"] = int(slow_mo)
    proxy = os.environ.get("WIZARDRY_JP_PROXY")
    if proxy:
        log(f"Routing through proxy: {proxy}")
        launch_kwargs["proxy"] = {"server": proxy}
    executable = os.environ.get("WIZARDRY_CHROMIUM_EXECUTABLE")
    if executable:
        launch_kwargs["executable_path"] = executable

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(locale="ja-JP")
        if BLOCK_ASSETS:
            block_heavy_assets(context)
        if DEBUG:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        rc = 3
        try:
            rc = run_flow(page, email, password)
        except PWTimeout as e:
            log(f"ERROR: timed out: {e}")
            shot(page, "error_timeout.png")
        except Exception as e:  # noqa: BLE001
            log(f"ERROR: unexpected: {e!r}")
            shot(page, "error_unexpected.png")
        finally:
            if DEBUG:
                context.tracing.stop(path=str(ARTIFACT_DIR / "trace_jp.zip"))
            if HOLD_SECONDS > 0:
                log(f"Holding browser open for {HOLD_SECONDS} seconds...")
                page.wait_for_timeout(HOLD_SECONDS * 1000)
            browser.close()
        return rc


if __name__ == "__main__":
    sys.exit(main())
