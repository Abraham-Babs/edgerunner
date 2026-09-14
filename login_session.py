import os
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath("browser_profile")
AUTH_STATE_FILE = os.path.abspath("browser_profile/auth_state.json")
os.makedirs(USER_DATA_DIR, exist_ok=True)

ITEL_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; itel A6611L Build/AP3A.240905.015.A2; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/131.0.6778.200 Mobile Safari/537.36"
)

print("[*] Launching browser window for login...")
print("[*] Window will stay open for up to 3 minutes or until you close it.")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,
        viewport={"width": 360, "height": 806},
        device_scale_factor=2.0,
        is_mobile=True,
        has_touch=True,
        user_agent=ITEL_USER_AGENT,
        locale="en-NG",
        timezone_id="Africa/Lagos",
        args=["--disable-blink-features=AutomationControlled"]
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://sports-exchange.internal/en-ng/virtuals")
    
    print("\n" + "="*50)
    print(">>> PLEASE LOG IN MANUALLY IN THE OPEN BROWSER WINDOW <<<")
    print("When logged in, you can close the browser or press Enter in this terminal.")
    print("="*50 + "\n")
    
    # Wait for user to log in - polling check for balance or user menu
    for _ in range(180):
        try:
            if page.is_closed():
                break
            # Check if login succeeded (profile icon or balance appears)
            if page.locator("text=LOGIN").count() == 0 and (
                page.locator("[data-testid='user-balance']").count() > 0 or 
                page.locator("text=Deposit").count() > 0 or
                "₦" in page.content()
            ):
                print("[+] Login detected! Saving session...")
                page.wait_for_timeout(3000)
                context.storage_state(path=AUTH_STATE_FILE)
                print(f"[+] Session saved successfully to {AUTH_STATE_FILE}")
                break
        except Exception:
            break
        page.wait_for_timeout(1000)
    
    try:
        context.storage_state(path=AUTH_STATE_FILE)
    except Exception:
        pass
    context.close()
    print("[*] Browser closed. Profile preserved.")
