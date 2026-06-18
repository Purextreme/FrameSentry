from __future__ import annotations

import asyncio
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "output" / "manual_checks" / "starrail_0612_v2" / "report.json"
SCREENSHOT = ROOT / "output" / "ui_check_playwright.png"
TABLE_SCREENSHOT = ROOT / "output" / "ui_check_event_table.png"
REVIEW_SCREENSHOT = ROOT / "output" / "ui_check_review_list.png"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


async def main() -> int:
    url = "http://127.0.0.1:8501/?report=" + urllib.parse.quote(str(REPORT.resolve()))
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = await browser.new_page(viewport={"width": 1440, "height": 1400})
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("text=事件概览", timeout=60_000)
        await page.wait_for_selector("text=截图复核", timeout=60_000)
        await page.wait_for_selector("img", timeout=60_000)
        await page.screenshot(path=str(SCREENSHOT), full_page=True)
        image_count = await page.locator("img").count()
        overview_count = await page.locator("text=事件概览").count()
        review_count = await page.locator("text=截图复核").count()
        old_selector_count = await page.locator("text=选择要查看的事件").count()
        raw_html_count = await page.locator("text=<td>").count()
        no_screenshot_count = await page.locator("text=该事件没有截图记录").count()
        await page.get_by_text("事件概览").scroll_into_view_if_needed()
        await page.screenshot(path=str(TABLE_SCREENSHOT), full_page=False)
        await page.get_by_text("截图复核").scroll_into_view_if_needed()
        await page.screenshot(path=str(REVIEW_SCREENSHOT), full_page=False)
        await browser.close()

    print(f"images={image_count}")
    print(f"event_overview_sections={overview_count}")
    print(f"review_sections={review_count}")
    print(f"old_selector_labels={old_selector_count}")
    print(f"raw_html_fragments={raw_html_count}")
    print(f"no_screenshot_messages={no_screenshot_count}")
    print(f"screenshot={SCREENSHOT}")
    print(f"table_screenshot={TABLE_SCREENSHOT}")
    print(f"review_screenshot={REVIEW_SCREENSHOT}")
    checks_passed = (
        image_count >= 1
        and overview_count >= 1
        and review_count >= 1
        and old_selector_count == 0
        and raw_html_count == 0
        and no_screenshot_count == 0
    )
    return 0 if checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
