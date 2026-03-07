"""
infra/validation/page_validator.py

Validates deployed pages (HTTP 200, Titles, CTAs).
Converted from V1 deploy/validator.py.
"""
from infrastructure.logger import get_logger

logger = get_logger("PageValidator")

class PageValidator:
    def validate_page(self, url: str) -> dict:
        """
        Validates target URL. Uses requests as fallback if playwright is unavailable.
        Returns structured validation dict.
        """
        logger.info(f"[PageValidator] Validating URL: {url}")
        
        report = {
            "url": url,
            "status": "pending",
            "http_200": False,
            "has_title": False,
            "has_cta": False,
            "details": []
        }

        try:
            from playwright.sync_api import sync_playwright
            return self._validate_playwright(url, report)
        except ImportError:
            logger.warning("[PageValidator] Playwright unavailable. Using 'requests' fallback.")
            return self._validate_requests(url, report)

    def _validate_playwright(self, url: str, report: dict) -> dict:
        from playwright.sync_api import sync_playwright
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                response = page.goto(url, timeout=15000)
                
                if response and response.ok:
                    report["http_200"] = True
                else:
                    report["details"].append(f"HTTP Error: {response.status if response else 'Unknown'}")
                    browser.close()
                    report["status"] = "failed"
                    return report
                
                title = page.title()
                if title:
                    report["has_title"] = True
                
                buy_button = page.get_by_text("Buy Now", exact=False).first
                if buy_button.is_visible():
                    report["has_cta"] = True
                else:
                    cta = page.locator(".cta-button").first
                    if cta.is_visible():
                        report["has_cta"] = True
                    else:
                        report["details"].append("No CTA element found.")
                
                browser.close()
                report["status"] = "passed" if (report["http_200"] and report["has_cta"]) else "warning"
                return report
                
        except Exception as e:
            logger.error(f"[PageValidator] Playwright Exception: {e}")
            report["details"].append(str(e))
            report["status"] = "error"
            return report

    def _validate_requests(self, url: str, report: dict) -> dict:
        import requests
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                report["http_200"] = True
                text = response.text
                
                if "<title>" in text.lower():
                    report["has_title"] = True
                
                if "Buy Now" in text or "cta-button" in text:
                    report["has_cta"] = True
                else:
                    report["details"].append("CTA 'Buy Now' or 'cta-button' not found in HTML.")
                
                report["status"] = "passed" if report["has_cta"] else "warning"
            else:
                report["details"].append(f"HTTP Status {response.status_code}")
                report["status"] = "failed"
                
        except Exception as e:
            logger.error(f"[PageValidator] Requests Exception: {e}")
            report["status"] = "error"
            report["details"].append(str(e))
            
        return report

# Singleton export
page_validator = PageValidator()

def validate_page(url: str) -> dict:
    """Wrapper for external calls."""
    return page_validator.validate_page(url)
