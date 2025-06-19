from playwright.sync_api import sync_playwright
import time

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
BRTI_URL = "https://www.cfbenchmarks.com/data/indices/BRTI"

def create_new_browser_session(p, logger=None):
    try:
        if logger:
            logger.info("Creating new browser session...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"User-Agent": USER_AGENT})
        if logger:
            logger.info("Navigating to BRTI page...")
        page.goto(BRTI_URL, timeout=20000)
        return browser, page
    except Exception as e:
        if logger:
            logger.error(f"Failed to create browser session: {e}")
        return None, None

def test_connection(page, logger=None):
    try:
        price_element = page.locator('div.leading-6 span').first
        price_element.wait_for(state='visible', timeout=10000)
        price_text = price_element.text_content()
        if not price_text or price_text.strip() == '':
            if logger:
                logger.warning("Price element found but empty content - possible shadow ban")
            return False
        price = float(price_text.replace('$', '').replace(',', ''))
        if price <= 0:
            if logger:
                logger.warning("Invalid price value - possible shadow ban")
            return False
        if logger:
            logger.info(f"Connection test successful - Price: ${price:,.2f}")
        return True
    except Exception as e:
        if logger:
            logger.error(f"Connection test failed: {e}")
        return False 