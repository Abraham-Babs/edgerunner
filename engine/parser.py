"""
engine/parser.py
----------------
Reads the live state of the SportsExchange league page directly from the browser DOM.

Three main jobs:
  1. Clean-up: Removes promotional iframes, pop-up dialogs, and blocking overlays
     that appear on the page and would interfere with clicking and reading.

  2. Countdown: Reads the round timer visible on the league page (e.g. '01:32')
     and returns the seconds remaining before the current fixtures kick off.
     This tells the runner whether there is still enough time to place a bet.

  3. Fixture scraping: Walks the DOM to find all visible match rows. For each
     match it extracts the team codes (e.g. 'LEE - LIV') and the three 1X2
     odds buttons (Home / Draw / Away). This data is then passed to the edge
     matcher to check if any of those live odds represent a positive-EV bet.
     Uses a TreeWalker scan so it finds match rows regardless of how the page
     HTML is nested or structured.
"""

import re
import time
from typing import Dict, List, Any, Optional, Set

CLEANUP_SCRIPT = """
() => {
    // 1. Remove free2play iframe and astro-island promotional wrapper
    document.querySelectorAll('astro-island, iframe[title="Free to Play"]').forEach(el => el.remove());
    document.querySelectorAll('iframe').forEach(f => {
        if (f.src.includes('free2play') || f.src.includes('premier-game') || f.src.includes('exchange-core-account')) {
            f.remove();
        }
    });
    // 2. Remove promo dialogs, penalty shootout / free to play modals, and backdrops
    document.querySelectorAll('div.dialog__paper, div.dialog__backdrop, div, section').forEach(el => {
        const txt = el.innerText || '';
        if (txt.includes('Welcome to Daily Free to Play') || txt.includes('PENALTY SHOOTOUT') || txt.includes('DAILY REWARDS FOR FREE') || txt.includes('Welcome back!')) {
            el.remove();
        }
    });
    // Click any modal close button if present
    document.querySelectorAll('button, div, span').forEach(el => {
        const aria = el.getAttribute('aria-label') || '';
        const cls = el.className || '';
        const txt = (el.innerText || '').trim();
        if (aria.toLowerCase().includes('close') || cls.toString().toLowerCase().includes('close') || txt === 'Close' || txt === '✕' || txt === '×') {
            try { el.click(); } catch(e) {}
        }
    });
    // 3. Auto-recover from temporary SportsExchange data reload overlay
    const refreshBtn = Array.from(document.querySelectorAll('button')).find(b => (b.innerText || '').includes('REFRESH PAGE'));
    if (refreshBtn) {
        refreshBtn.click();
    }
}
"""

def clean_page(page):
    """Clean promotional iframes and blocking backdrops."""
    try:
        page.evaluate(CLEANUP_SCRIPT)
    except Exception:
        pass

def parse_round_countdown(page) -> Optional[int]:
    """
    Extract remaining seconds from countdown text (e.g., '01:45', '00:32').
    Returns total seconds remaining, or None if not found.
    """
    try:
        time_text = page.evaluate("""() => {
            const spans = Array.from(document.querySelectorAll('span, div, p'));
            for (const s of spans) {
                const txt = s.innerText.trim();
                if (/^\\d{2}:\\d{2}$/.test(txt)) {
                    return txt;
                }
            }
            return null;
        }""")
        if time_text:
            parts = time_text.split(":")
            return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        pass
    return None

def select_week_tab(page, week: str) -> bool:
    """Clicks the specified round button (e.g. 'Week 35') at the top of the screen to reveal its fixtures."""
    try:
        tab_btn = page.locator(f"button:has-text('{week}')").first
        if tab_btn.count() > 0:
            try:
                tab_btn.scroll_into_view_if_needed(timeout=600)
            except Exception:
                pass
            tab_btn.click(force=True)
            page.wait_for_timeout(random.randint(450, 750))
            return True
    except Exception:
        pass
    return False

def extract_current_market_rows(page) -> Dict[str, Dict[str, Any]]:
    """
    Extracts all visible match fixtures, their week identifier, and their odds buttons across all 4 visible rounds.
    Returns:
      {
        'Week 8 | LEE - BOU': { 'week': 'Week 8', 'match_name': 'LEE - BOU', 'odds': [1.45, 3.20] }
      }
    """
    clean_page(page)
    js_extract = """
    () => {
        const weekHeaders = Array.from(document.querySelectorAll('p')).filter(p => {
            return /^Week\\s+\\d+$/i.test((p.innerText || '').trim()) && !p.closest('button');
        });
        const unique = {};
        for (let i = 0; i < weekHeaders.length; i++) {
            const h = weekHeaders[i];
            const wName = h.innerText.trim();
            const nextH = weekHeaders[i + 1];
            const startY = h.getBoundingClientRect().top + window.scrollY;
            const endY = nextH ? (nextH.getBoundingClientRect().top + window.scrollY) : 999999;
            
            const rows = Array.from(document.querySelectorAll('div')).filter(d => {
                if (d.children.length > 5) return false;
                const txt = d.innerText || '';
                const codes = txt.match(/[A-Z]{3}/g) || [];
                const rect = d.getBoundingClientRect();
                const absY = rect.top + window.scrollY;
                return codes.length === 2 && txt.includes('-') && absY >= (startY - 10) && absY < endY;
            });
            
            for (const r of rows) {
                const codes = (r.innerText || '').match(/[A-Z]{3}/g) || [];
                if (codes.length === 2) {
                    const mKey = codes[0] + ' - ' + codes[1];
                    const btns = Array.from(r.querySelectorAll('button[data-testid="match-odd"]'))
                        .map(b => parseFloat(b.innerText.trim().replace(/,/g, '')))
                        .filter(v => !isNaN(v));
                    if (btns.length >= 1 && btns.length <= 28) {
                        const fullKey = wName + ' | ' + mKey;
                        if (!unique[fullKey]) {
                            unique[fullKey] = {
                                week: wName,
                                match_name: mKey,
                                odds: btns
                            };
                        }
                    }
                }
            }
        }
        return unique;
    }
    """
    try:
        return page.evaluate(js_extract) or {}
    except Exception:
        return {}

def extract_visible_weeks(page) -> Set[str]:
    """Extracts the set of visible round week headers currently displayed on screen."""
    clean_page(page)
    try:
        weeks = page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'));
            const res = [];
            for (const b of btns) {
                const txt = (b.innerText || '').trim();
                const m = txt.match(/^Week\\s+(\\d+)$/i);
                if (m) res.push('Week ' + m[1]);
            }
            return res;
        }""")
        if weeks:
            return set(weeks)
    except Exception:
        pass
    rows = extract_current_market_rows(page)
    return {data["week"] for data in rows.values() if data.get("week") and data.get("week") != "Current"}

def extract_all_markets(page, matcher=None, league_key: Optional[str] = None, target_week: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Crawls across market tabs to extract live odds for confirmed outcome keys.
    If target_week is provided, explicitly taps that week's round button first.
    """
    clean_page(page)
    if target_week:
        select_week_tab(page, target_week)
    clean_page(page)
    results = []

    # 1. First extract default active 1X2 tab without clicking
    initial_fixtures = extract_current_market_rows(page)
    active_matches = set()
    for full_key, data in initial_fixtures.items():
        m_week = data.get("week", "")
        m_name = data.get("match_name", "")
        if m_name:
            active_matches.add(m_name)
        odds_list = data.get("odds", [])
        for idx, key in enumerate(["1x2_1_val", "1x2_x_val", "1x2_2_val"]):
            if idx < len(odds_list):
                results.append({
                    "week": m_week,
                    "match_name": m_name,
                    "category": "Popular",
                    "tab_name": "1X2",
                    "outcome_key": key,
                    "odds": odds_list[idx],
                    "btn_idx": idx
                })

    def has_edge_for_keys(keys: List[str]) -> bool:
        if not matcher or not league_key or not active_matches:
            return True
        for m in active_matches:
            for k in keys:
                if matcher.find_edge(league_key, m, k):
                    return True
        return False

    def _scrape_tab(cat_name: str, tab_name: str, outcome_keys: List[str]):
        try:
            tab_btn = page.locator(f"li:has-text('{tab_name}'), p:has-text('{tab_name}'), button:has-text('{tab_name}')").first
            if tab_btn.count() > 0:
                try:
                    tab_btn.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                if tab_btn.is_visible(timeout=1000):
                    tab_btn.click(force=True)
                    time.sleep(0.4)
                    
                    # Verify active market name updated
                    market_span = page.locator('span[data-testid="selected-market-name"]').first
                    if market_span.count() > 0:
                        cur_m = (market_span.inner_text() or '').strip()
                        if tab_name.lower() not in cur_m.lower() and cur_m.lower() not in tab_name.lower():
                            tab_btn.click(force=True)
                            time.sleep(0.3)
                    
                    fixtures = extract_current_market_rows(page)
                    for full_key, data in fixtures.items():
                        m_week = data.get("week", "")
                        m_name = data.get("match_name", "")
                        odds_list = data.get("odds", [])
                        for idx, key in enumerate(outcome_keys):
                            if idx < len(odds_list):
                                results.append({
                                    "week": m_week,
                                    "match_name": m_name,
                                    "category": cat_name,
                                    "tab_name": tab_name,
                                    "outcome_key": key,
                                    "odds": odds_list[idx],
                                    "btn_idx": idx
                                })
        except Exception:
            pass

    def _open_category(cat_name: str) -> bool:
        try:
            mm = page.locator("text='More Markets'").first
            if mm.count() > 0:
                try:
                    mm.scroll_into_view_if_needed(timeout=500)
                except Exception:
                    pass
                mm.click(force=True)
                time.sleep(0.3)
                cat = page.locator(f"li:has-text('{cat_name}')").first
                if cat.count() > 0:
                    try:
                        cat.scroll_into_view_if_needed(timeout=1000)
                    except Exception:
                        pass
                    if cat.is_visible(timeout=1000):
                        cat.click(force=True)
                        time.sleep(0.4)
                        return True
        except Exception:
            pass
        return False

    # Popular category remaining tabs
    POPULAR_OTHER_TABS = {
        "Double Chance": ["double_chance_1x_val", "double_chance_12_val", "double_chance_x2_val"],
        "O/U 2.5": ["o_u_2_5_ov_val", "o_u_2_5_un_val"],
        "GG/NG": ["gg_ng_gg_val", "gg_ng_ng_val"],
        "Correct Score": [
            "correct_score_1_0_val", "correct_score_2_0_val", "correct_score_2_1_val",
            "correct_score_3_0_val", "correct_score_3_1_val", "correct_score_3_2_val",
            "correct_score_4_0_val", "correct_score_4_1_val", "correct_score_4_2_val",
            "correct_score_5_0_val", "correct_score_5_1_val", "correct_score_6_0_val",
            "correct_score_0_0_val", "correct_score_1_1_val", "correct_score_2_2_val",
            "correct_score_3_3_val",
            "correct_score_0_1_val", "correct_score_0_2_val", "correct_score_1_2_val",
            "correct_score_0_3_val", "correct_score_1_3_val", "correct_score_0_4_val",
            "correct_score_2_3_val", "correct_score_0_5_val", "correct_score_1_4_val",
            "correct_score_2_4_val", "correct_score_0_6_val", "correct_score_1_5_val"
        ]
    }
    for tab_name, keys in POPULAR_OTHER_TABS.items():
        if has_edge_for_keys(keys):
            _scrape_tab("Popular", tab_name, keys)

    # More Markets categories
    CATEGORIES = {
        "Over/Under": {
            "O/U 1.5": ["o_u_1_5_ov_val", "o_u_1_5_un_val"],
            "O/U 3.5": ["o_u_3_5_ov_val", "o_u_3_5_un_val"],
            "O/U 4.5": ["o_u_4_5_ov_val", "o_u_4_5_un_val"]
        },
        "Home Goals": {
            "Home O/U 0.5": ["home_o_u_0_5_ov_val", "home_o_u_0_5_un_val"],
            "Home O/U 1.5": ["home_o_u_1_5_ov_val", "home_o_u_1_5_un_val"],
            "Home O/U 2.5": ["home_o_u_2_5_ov_val", "home_o_u_2_5_un_val"],
            "Home O/U 3.5": ["home_o_u_3_5_ov_val"],
            "Home Clean Sheet": ["home_clean_sheet_yes_val", "home_clean_sheet_no_val"]
        },
        "Away Goals": {
            "Away O/U 0.5": ["away_o_u_0_5_ov_val", "away_o_u_0_5_un_val"],
            "Away O/U 1.5": ["away_o_u_1_5_ov_val", "away_o_u_1_5_un_val"],
            "Away O/U 2.5": ["away_o_u_2_5_ov_val"],
            "Away O/U 3.5": ["away_o_u_3_5_ov_val"],
            "Away Clean Sheet": ["away_clean_sheet_yes_val", "away_clean_sheet_no_val"]
        },
        "1X2 & GG/NG": {
            "1X2 & GG": [
                "1x2_gg_1_gg_val", "1x2_gg_1_ng_val",
                "1x2_gg_x_gg_val", "1x2_gg_x_ng_val",
                "1x2_gg_2_gg_val", "1x2_gg_2_ng_val"
            ]
        },
        "1X2 & O/U 1.5": {
            "1X2 & O/U 1.5": [
                "1x2_o_u_1_5_1_ov_val", "1x2_o_u_1_5_1_un_val",
                "1x2_o_u_1_5_x_ov_val", "1x2_o_u_1_5_x_un_val",
                "1x2_o_u_1_5_2_ov_val", "1x2_o_u_1_5_2_un_val"
            ]
        },
        "1X2 & O/U 2.5": {
            "1X2 & O/U 2.5": [
                "1x2_o_u_2_5_1_ov_val", "1x2_o_u_2_5_1_un_val",
                "1x2_o_u_2_5_x_ov_val", "1x2_o_u_2_5_x_un_val",
                "1x2_o_u_2_5_2_ov_val", "1x2_o_u_2_5_2_un_val"
            ]
        },
        "HT/FT": {
            "HT/FT": [
                "ht_ft_1_1_val", "ht_ft_1_x_val", "ht_ft_1_2_val",
                "ht_ft_x_1_val", "ht_ft_x_x_val", "ht_ft_x_2_val",
                "ht_ft_2_1_val", "ht_ft_2_x_val", "ht_ft_2_2_val"
            ]
        },
        "Half Time": {
            "HT 1X2": ["ht_1x2_1_val", "ht_1x2_x_val", "ht_1x2_2_val"],
            "Goal Goal HT": ["goal_goal_ht_yes_val", "goal_goal_ht_no_val"]
        },
        "Total Goals": {
            "Total Goals": [
                "total_goals_0_val", "total_goals_1_val", "total_goals_2_val",
                "total_goals_3_val", "total_goals_4_val", "total_goals_5_val",
                "total_goals_6_val"
            ]
        },
        "Correct Score": {
            "HT Correct Score": [
                "ht_correct_score_1_0_val", "ht_correct_score_2_0_val", "ht_correct_score_2_1_val", "ht_correct_score_3_0_val",
                "ht_correct_score_0_0_val", "ht_correct_score_1_1_val",
                "ht_correct_score_0_1_val", "ht_correct_score_0_2_val", "ht_correct_score_1_2_val", "ht_correct_score_0_3_val"
            ]
        }
    }

    for cat_name, tabs in CATEGORIES.items():
        all_cat_keys = [k for keys in tabs.values() for k in keys]
        if not has_edge_for_keys(all_cat_keys):
            continue
        if _open_category(cat_name):
            for tab_name, keys in tabs.items():
                if has_edge_for_keys(keys):
                    _scrape_tab(cat_name, tab_name, keys)

    return results

def extract_live_matches_and_buttons(page) -> List[Dict[str, Any]]:
    """Legacy helper returning 1X2 matches for backwards compatibility."""
    clean_page(page)
    all_markets = extract_all_markets(page)
    grouped = {}
    for item in all_markets:
        m = item["match_name"]
        if m not in grouped:
            grouped[m] = {"match_name": m, "odds_1": 0.0, "odds_x": 0.0, "odds_2": 0.0}
        if item["outcome_key"] == "1x2_1_val":
            grouped[m]["odds_1"] = item["odds"]
        elif item["outcome_key"] == "1x2_x_val":
            grouped[m]["odds_x"] = item["odds"]
        elif item["outcome_key"] == "1x2_2_val":
            grouped[m]["odds_2"] = item["odds"]
    return list(grouped.values())

