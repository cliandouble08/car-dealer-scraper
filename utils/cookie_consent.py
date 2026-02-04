"""
Cookie Consent Handler Module

Handles dismissing cookie consent banners/popups before main scraping operations.
Supports popular consent management platforms like OneTrust, CookieBot, TrustArc, etc.
"""

import asyncio
from typing import Dict, List, Optional, Any
from playwright.async_api import Page, Frame, ElementHandle


# Default selectors for popular cookie consent frameworks
DEFAULT_COOKIE_SELECTORS = [
    # OneTrust
    '#onetrust-accept-btn-handler',
    '#onetrust-banner-sdk button[id*="accept"]',
    '.onetrust-close-btn-handler',
    
    # CookieBot
    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
    '#CybotCookiebotDialogBodyButtonAccept',
    '#CybotCookiebotDialogBodyLevelButtonAccept',
    
    # TrustArc
    '#truste-consent-button',
    '.trustarc-agree-btn',
    '.pdynamicbutton .call',
    
    # Cookie Law Info (WordPress plugin)
    '#cookielawinfo-checkbox-accept',
    '#cookie_action_close_header',
    '.cli-plugin-button.cli_action_button',
    
    # HubSpot
    '#hs-eu-confirmation-button',
    '#hs-eu-cookie-confirmation-accept',
    
    # Osano Cookie Consent
    '.cc-accept-all',
    '.cc-btn.cc-allow',
    '.cc-compliance .cc-btn',
    
    # Quantcast
    '.qc-cmp2-summary-buttons button[mode="primary"]',
    '#qc-cmp2-ui button.css-47sehv',
    
    # Didomi
    '#didomi-notice-agree-button',
    '.didomi-continue-without-agreeing',
    
    # Termly
    '[data-tid="banner-accept"]',
    '.t-acceptAllButton',
    
    # Generic data-testid patterns
    '[data-testid="cookie-accept"]',
    '[data-testid="accept-cookies"]',
    '[data-testid="cookie-banner-accept"]',
    '[data-testid="GDPR-accept"]',
    
    # Generic text-based patterns (Playwright :has-text)
    'button:has-text("Accept All")',
    'button:has-text("Accept all")',
    'button:has-text("Accept All Cookies")',
    'button:has-text("Accept Cookies")',
    'button:has-text("Allow All")',
    'button:has-text("Allow all")',
    'button:has-text("Allow All Cookies")',
    'button:has-text("I Accept")',
    'button:has-text("I Agree")',
    'button:has-text("Agree")',
    'button:has-text("Agree & Continue")',
    'button:has-text("Got it")',
    'button:has-text("OK")',
    'button:has-text("Continue")',
    'a:has-text("Accept All")',
    'a:has-text("I Agree")',
    
    # Generic class/ID patterns
    '[class*="cookie-consent"] button[class*="accept"]',
    '[class*="cookie-banner"] button[class*="accept"]',
    '[class*="cookie-notice"] button[class*="accept"]',
    '[class*="cookieConsent"] button[class*="accept"]',
    '[class*="gdpr"] button[class*="accept"]',
    '[class*="privacy-banner"] button[class*="accept"]',
    '[id*="cookie-accept"]',
    '[id*="accept-cookie"]',
    '[id*="cookieAccept"]',
    '[id*="acceptCookie"]',
    
    # Fallback generic patterns
    '[class*="cookie"] button',
    '[id*="cookie"] button',
    '.consent-banner button',
    '.privacy-notice button',
]

# Selectors to detect if a cookie banner is present
BANNER_DETECTION_SELECTORS = [
    '#onetrust-banner-sdk',
    '#CybotCookiebotDialog',
    '#truste-consent-track',
    '.qc-cmp2-container',
    '#didomi-host',
    '[class*="cookie-banner"]',
    '[class*="cookie-consent"]',
    '[class*="cookie-notice"]',
    '[class*="cookieBanner"]',
    '[class*="cookieConsent"]',
    '[id*="cookie-banner"]',
    '[id*="cookie-consent"]',
    '[role="dialog"][class*="cookie"]',
    '[aria-label*="cookie" i]',
    '[aria-label*="consent" i]',
]


class CookieConsentHandler:
    """
    Handles cookie consent banners/popups for web scraping.
    
    Supports:
    - Popular consent management platforms (OneTrust, CookieBot, TrustArc, etc.)
    - Generic cookie banners with common button patterns
    - Consent banners inside iframes
    - Configurable behavior via config dict
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the cookie consent handler.
        
        Args:
            config: Configuration dict with optional 'cookie_consent' section.
                   Falls back to defaults if not provided.
        """
        self.config = config or {}
        cookie_config = self.config.get('cookie_consent', {})
        
        # Whether cookie handling is enabled
        self.enabled = cookie_config.get('enabled', True)
        
        # Get selectors from config or use defaults
        self.selectors = cookie_config.get('selectors', DEFAULT_COOKIE_SELECTORS)
        
        # Interaction settings
        interactions = cookie_config.get('interactions', {})
        self.wait_for_banner = interactions.get('wait_for_banner', 2)
        self.wait_after_click = interactions.get('wait_after_click', 0.5)
        self.max_retries = interactions.get('max_retries', 2)
        self.check_iframes = interactions.get('check_iframes', True)
        
        # Debug mode
        self.debug = self.config.get('debug', False)
    
    def _log(self, message: str):
        """Log debug messages if debug mode is enabled."""
        if self.debug:
            print(f"  [CookieConsent] {message}")
    
    async def dismiss_cookie_banner(self, page: Page) -> bool:
        """
        Main entry point: Attempt to dismiss any cookie consent banner.
        
        Args:
            page: Playwright Page object
            
        Returns:
            True if a banner was found and dismissed, False otherwise
        """
        if not self.enabled:
            self._log("Cookie consent handling is disabled")
            return False
        
        self._log("Checking for cookie consent banner...")
        
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                self._log(f"Retry attempt {attempt}/{self.max_retries}")
            
            # First, try to find and click on the main page
            dismissed = await self._try_dismiss_on_page(page)
            if dismissed:
                return True
            
            # If not found on main page, check iframes
            if self.check_iframes:
                dismissed = await self._try_dismiss_in_iframes(page)
                if dismissed:
                    return True
            
            # Wait a bit before retrying (banner might still be loading)
            if attempt < self.max_retries:
                await asyncio.sleep(self.wait_for_banner)
        
        self._log("No cookie banner found or unable to dismiss")
        return False
    
    async def _try_dismiss_on_page(self, page: Page) -> bool:
        """
        Try to find and click a cookie consent button on the main page.
        
        Args:
            page: Playwright Page object
            
        Returns:
            True if successfully dismissed, False otherwise
        """
        for selector in self.selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    self._log(f"Found cookie button with selector: {selector}")
                    
                    # Click the button
                    await element.click()
                    self._log("Clicked cookie consent button")
                    
                    # Wait for banner to dismiss
                    await asyncio.sleep(self.wait_after_click)
                    
                    # Verify it was dismissed
                    if await self._verify_dismissed(page, element):
                        self._log("Cookie banner successfully dismissed")
                        return True
                    else:
                        self._log("Banner may not be fully dismissed, continuing...")
                        return True  # Still return True as we clicked
                        
            except Exception as e:
                self._log(f"Error with selector '{selector}': {e}")
                continue
        
        return False
    
    async def _try_dismiss_in_iframes(self, page: Page) -> bool:
        """
        Try to find and click cookie consent buttons inside iframes.
        
        Many consent management platforms render their banners in iframes.
        
        Args:
            page: Playwright Page object
            
        Returns:
            True if successfully dismissed, False otherwise
        """
        try:
            frames = page.frames
            self._log(f"Checking {len(frames)} frames for cookie banners")
            
            for frame in frames:
                # Skip the main frame (already checked)
                if frame == page.main_frame:
                    continue
                
                # Check if this frame might be a consent frame
                frame_url = frame.url.lower()
                if any(keyword in frame_url for keyword in ['consent', 'cookie', 'gdpr', 'privacy', 'onetrust', 'cookiebot', 'trustarc']):
                    self._log(f"Found potential consent frame: {frame_url[:50]}...")
                    
                    dismissed = await self._try_dismiss_in_frame(frame)
                    if dismissed:
                        return True
                
                # Also try frames without keyword matches (some use generic URLs)
                dismissed = await self._try_dismiss_in_frame(frame)
                if dismissed:
                    return True
                    
        except Exception as e:
            self._log(f"Error checking iframes: {e}")
        
        return False
    
    async def _try_dismiss_in_frame(self, frame: Frame) -> bool:
        """
        Try to dismiss cookie consent in a specific frame.
        
        Args:
            frame: Playwright Frame object
            
        Returns:
            True if successfully dismissed, False otherwise
        """
        for selector in self.selectors:
            try:
                element = await frame.query_selector(selector)
                if element and await element.is_visible():
                    self._log(f"Found cookie button in iframe with selector: {selector}")
                    
                    await element.click()
                    self._log("Clicked cookie consent button in iframe")
                    
                    await asyncio.sleep(self.wait_after_click)
                    return True
                    
            except Exception:
                continue
        
        return False
    
    async def _verify_dismissed(self, page: Page, clicked_element: ElementHandle) -> bool:
        """
        Verify that the cookie banner was actually dismissed.
        
        Args:
            page: Playwright Page object
            clicked_element: The element that was clicked
            
        Returns:
            True if banner appears to be dismissed, False otherwise
        """
        try:
            # Check if the clicked element is no longer visible
            if not await clicked_element.is_visible():
                return True
            
            # Check if common banner containers are gone
            for selector in BANNER_DETECTION_SELECTORS[:5]:  # Check first few
                try:
                    banner = await page.query_selector(selector)
                    if banner and await banner.is_visible():
                        return False
                except Exception:
                    continue
            
            return True
            
        except Exception:
            # Element might be detached (which means it was removed - good!)
            return True
    
    async def wait_for_banner_and_dismiss(self, page: Page, timeout: float = None) -> bool:
        """
        Wait for a cookie banner to appear, then dismiss it.
        
        Useful when you know a banner will appear but it hasn't loaded yet.
        
        Args:
            page: Playwright Page object
            timeout: Max seconds to wait for banner (defaults to wait_for_banner config)
            
        Returns:
            True if banner was found and dismissed, False otherwise
        """
        timeout = timeout or self.wait_for_banner
        
        self._log(f"Waiting up to {timeout}s for cookie banner to appear...")
        
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            # Check if any banner is visible
            for selector in BANNER_DETECTION_SELECTORS:
                try:
                    banner = await page.query_selector(selector)
                    if banner and await banner.is_visible():
                        self._log(f"Cookie banner detected: {selector}")
                        return await self.dismiss_cookie_banner(page)
                except Exception:
                    continue
            
            await asyncio.sleep(0.2)
        
        self._log("No cookie banner appeared within timeout")
        return False
    
    async def is_banner_present(self, page: Page) -> bool:
        """
        Check if a cookie consent banner is currently visible.
        
        Args:
            page: Playwright Page object
            
        Returns:
            True if a banner is detected, False otherwise
        """
        for selector in BANNER_DETECTION_SELECTORS:
            try:
                banner = await page.query_selector(selector)
                if banner and await banner.is_visible():
                    return True
            except Exception:
                continue
        
        return False
