"""
engine/human_interaction.py
----------------------------
Makes the browser session look and feel like a real person using a phone.

Automated bots are often detected by the precision and speed of their
actions — clicking the exact center of buttons every time, typing at
machine speed, never pausing to look around. This module introduces
realistic imperfection at every step:

  - Pauses    : Random wait times between actions (simulating reading / thinking).
  - Scrolling : Natural thumb-flick scroll movements up and down the page.
  - Typing    : Characters are entered one at a time with variable key delays,
                mimicking how someone types on a mobile keyboard.
  - Tapping   : Instead of clicking the exact geometric center of a button,
                each tap lands at a slightly random position within the button
                area, with a short pre-tap hover delay before the touch registers.
"""

import time
import random
from typing import Any

def human_pause(min_sec: float = 0.8, max_sec: float = 2.2):
    """Simulate human visual scanning or thinking pause."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)

def human_scroll(page, distance: int = 150):
    """Simulate a natural mobile thumb flick/scroll."""
    try:
        delta_y = distance * random.choice([1, -1]) if distance > 0 else distance
        page.mouse.wheel(0, delta_y)
        time.wait_for_timeout(random.randint(300, 700)) if hasattr(page, 'wait_for_timeout') else time.sleep(0.5)
    except Exception:
        pass

def human_tap(element, page: Any = None):
    """
    Tap an element with slight spatial jitter (not exact center)
    and natural touch-down / touch-up timing.
    Automatically scrolls element into view if needed.
    """
    try:
        try:
            element.scroll_into_view_if_needed(timeout=2000)
            time.sleep(random.uniform(0.1, 0.25))
        except Exception:
            pass

        box = element.bounding_box()
        if box:
            # Jitter within middle 60% of button area
            jitter_x = box["x"] + box["width"] * random.uniform(0.2, 0.8)
            jitter_y = box["y"] + box["height"] * random.uniform(0.2, 0.8)
            
            # Short pre-touch hover/aim
            time.sleep(random.uniform(0.15, 0.35))
            
            if page:
                page.mouse.click(jitter_x, jitter_y, delay=random.randint(40, 110))
            else:
                element.click(force=True)
        else:
            element.click(force=True)
    except Exception:
        try:
            element.click(force=True)
        except Exception:
            pass


def human_type(input_element, text: str):
    """
    Simulate natural mobile keypad typing with variable inter-key delays.
    """
    try:
        input_element.click()
        time.sleep(random.uniform(0.2, 0.5))
        # Clear existing
        input_element.fill("")
        time.sleep(random.uniform(0.1, 0.25))
        for char in str(text):
            input_element.type(char, delay=random.randint(110, 260))
            time.sleep(random.uniform(0.05, 0.15))
    except Exception:
        input_element.fill(str(text))
