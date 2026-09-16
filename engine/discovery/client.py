"""
engine/discovery/client.py
--------------------------
High-performance, strictly stateless unauthenticated HTTP discovery client
for SportsExchange scheduled virtual football.

Transport Architecture:
1. Primary Transport: HTTP/2 with modern mobile Chrome headers (Sec-CH-UA, Sec-Fetch)
   enabling true multiplexing over a single persistent connection.
2. Fallback Transport: HTTP/1.1 with keep-alive connection pooling if H2 drops or resets.
3. Resilient against variable network latency (e.g. Nigerian ISPs).
4. Selective Area fetching: Area 2 (O/U 1.5, 3.5, 4.5) only queried when active
   matches have confirmed edges.
5. Server clock skew synchronization for millisecond-accurate kickoff epochs.
"""

import time
import ssl
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional

import httpx

from engine.config import LEAGUES
from engine.discovery.market_mapping import (
    map_selection_to_outcome,
    OUTCOME_TO_UI_METADATA,
)

BASE_URL = "https://sports-exchange.internal/en-ng/virtuals/api"

NIGERIAN_MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 15; itel A6611L Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.200 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; TECNO KI7 Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.14 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Infinix X669 Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.122 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-A145F Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.102 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; 22120RN86G Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36"
]

LEAGUE_SLUG_MAP = {
    "league_en": "premier-league",
    "league_es": "primera-liga",
    "league_it": "serie-league",
    "league_de": "bundes-league",
}

AREA_2_OUTCOME_KEYS = {
    "o_u_1_5_ov_val", "o_u_1_5_un_val",
    "o_u_3_5_ov_val", "o_u_3_5_un_val",
    "o_u_4_5_ov_val", "o_u_4_5_un_val",
}

class PublicDiscoveryClient:
    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout
        self.clock_skew_sec: float = 0.0
        self.last_skew_sync: float = 0.0

        ctx = ssl.create_default_context()
        ctx.set_alpn_protocols(["h2", "http/1.1"])

        # Primary H2 client
        self._client_h2 = httpx.Client(
            http2=True,
            verify=ctx,
            cookies=None,
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        )
        # Fallback HTTP/1.1 client
        self._client_h1 = httpx.Client(
            http2=False,
            cookies=None,
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        )
        self.active_protocol = "HTTP/2"
        self.sync_clock_skew()

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://sports-exchange.internal",
            "Referer": "https://sports-exchange.internal/en-ng/virtuals",
            "User-Agent": random.choice(NIGERIAN_MOBILE_USER_AGENTS),
            "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?1",
            "Sec-Ch-Ua-Platform": '"Android"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def sync_clock_skew(self) -> float:
        """Measures clock skew between server and local host epoch in seconds."""
        try:
            t_local = time.time()
            res = self._post_or_get(f"{BASE_URL}/server-time", method="GET")
            if res and res.status_code == 200:
                server_epoch_ms = res.json().get("data", 0)
                if server_epoch_ms > 0:
                    local_ms = int(t_local * 1000)
                    self.clock_skew_sec = (server_epoch_ms - local_ms) / 1000.0
                    self.last_skew_sync = t_local
        except Exception:
            pass
        return self.clock_skew_sec

    def get_server_epoch(self) -> float:
        """Current server time estimated via local epoch + synchronized skew."""
        return time.time() + self.clock_skew_sec

    def _post_or_get(self, url: str, method: str = "POST", data: dict = None) -> Optional[httpx.Response]:
        """Tries HTTP/2 first; falls back to HTTP/1.1 if connection drops or resets."""
        headers = self._get_headers()
        # 1. Attempt H2
        try:
            if method == "POST":
                res = self._client_h2.post(url, headers=headers, data=data)
            else:
                res = self._client_h2.get(url, headers=headers)
            if res.status_code == 200:
                self.active_protocol = "HTTP/2"
                return res
        except Exception:
            pass

        # 2. Resilient fallback to HTTP/1.1
        try:
            if method == "POST":
                res = self._client_h1.post(url, headers=headers, data=data)
            else:
                res = self._client_h1.get(url, headers=headers)
            if res.status_code == 200:
                self.active_protocol = "HTTP/1.1"
                return res
        except Exception:
            pass

        return None

    def fetch_league_sync(self, slug: str, area: str = "1") -> Optional[dict]:
        """Fetch raw sync payload for a specific league and market area."""
        res = self._post_or_get(
            f"{BASE_URL}/scheduled-competitions/leagues/{slug}/sync",
            method="POST",
            data={"includeEvents": "true", "areas": area},
        )
        if res and res.status_code == 200:
            try:
                return res.json()
            except Exception:
                pass
        return None

    def discover_league_candidates(
        self,
        league_key: str,
        matcher,
        profile_name: str = "ultra_conservative",
        allow_conservative: bool = False,
    ) -> Dict[str, Any]:
        slug = LEAGUE_SLUG_MAP.get(league_key, league_key)
        
        # 1. Fetch Area 1 (Popular: 1X2, Double Chance, O/U 2.5, GG/NG)
        data_area1 = self.fetch_league_sync(slug, "1")
        if not data_area1 or "rounds" not in data_area1:
            return {"league": league_key, "rounds": {}, "candidates": []}

        # 2. Check if any active match actually has confirmed edges in Area 2
        active_match_names = set()
        for rnd in data_area1.get("rounds", []):
            for ev in rnd.get("events", []):
                parts = ev.get("participants", [])
                if len(parts) >= 2:
                    active_match_names.add(f"{parts[0].get('name')} - {parts[1].get('name')}".strip())

        needs_area_2 = False
        for m_name in active_match_names:
            for outcome_k in AREA_2_OUTCOME_KEYS:
                if matcher.find_edge(league_key, m_name, outcome_k, profile_name=profile_name):
                    needs_area_2 = True
                    break
            if needs_area_2:
                break

        # 3. Selectively fetch Area 2 only when edges exist for active matches
        data_area2 = self.fetch_league_sync(slug, "2") if needs_area_2 else None
        area2_odds_map = {}
        if data_area2 and "rounds" in data_area2:
            for r in data_area2.get("rounds", []):
                r_id = r.get("id")
                for ev in r.get("events", []):
                    ev_id = ev.get("id")
                    area2_odds_map[(r_id, ev_id)] = ev.get("oddsByMarket", {})

        rounds_meta = {}
        candidates = []
        now_server = self.get_server_epoch()

        for rnd in data_area1.get("rounds", []):
            round_id = rnd.get("id")
            raw_name = rnd.get("name", "")
            week_str = f"Week {raw_name}" if not str(raw_name).startswith("Week") else str(raw_name)
            date_ms = rnd.get("dateMs", 0)
            kickoff_epoch = (date_ms / 1000.0) if date_ms > 0 else (now_server + 180)
            remaining_sec = max(0.0, kickoff_epoch - now_server)

            rounds_meta[week_str] = {
                "round_id": round_id,
                "week": week_str,
                "kickoff_epoch": kickoff_epoch,
                "remaining_sec": remaining_sec,
                "betting_duration": rnd.get("bettingDuration", 150),
            }

            # Skip rounds that have already kicked off
            if remaining_sec <= 0.0:
                continue

            for ev in rnd.get("events", []):
                ev_id = ev.get("id")
                participants = ev.get("participants", [])
                if len(participants) < 2:
                    continue
                match_name = f"{participants[0].get('name')} - {participants[1].get('name')}".strip()

                combined_odds = dict(ev.get("oddsByMarket", {}))
                if (round_id, ev_id) in area2_odds_map:
                    combined_odds.update(area2_odds_map[(round_id, ev_id)])

                for m_id, selections in combined_odds.items():
                    for sel_id, sel_data in selections.items():
                        outcome_key = map_selection_to_outcome(m_id, sel_id)
                        if not outcome_key:
                            continue

                        live_odds = float(sel_data.get("value", 0.0))
                        if live_odds <= 1.0:
                            continue

                        edge_data = matcher.find_edge(league_key, match_name, outcome_key, profile_name=profile_name)
                        if not edge_data and allow_conservative:
                            edge_data = matcher.find_edge(league_key, match_name, outcome_key, profile_name="conservative")

                        if edge_data:
                            mu_phat = edge_data["mu_phat"]
                            live_ev = (mu_phat * live_odds) - 1.0
                            if live_ev >= 0.05:
                                ui_meta = OUTCOME_TO_UI_METADATA.get(outcome_key, {"category": "Popular", "tab_name": "1X2", "btn_idx": 0})
                                candidates.append({
                                    "league": league_key,
                                    "week": week_str,
                                    "round_id": round_id,
                                    "event_id": ev_id,
                                    "selection_id": sel_data.get("id"),
                                    "selection_type_id": sel_id,
                                    "market_id": m_id,
                                    "match_name": match_name,
                                    "outcome": outcome_key,
                                    "raw_odds": live_odds,
                                    "mu_phat": mu_phat,
                                    "min_edge": live_ev,
                                    "oos_edge": edge_data.get("oos_edge", 0.0),
                                    "n_train": edge_data.get("n_train", 0),
                                    "kickoff_epoch": kickoff_epoch,
                                    "category": ui_meta["category"],
                                    "tab_name": ui_meta["tab_name"],
                                    "btn_idx": ui_meta["btn_idx"],
                                })

        return {
            "league": league_key,
            "rounds": rounds_meta,
            "candidates": candidates,
        }

    def discover_all_leagues(
        self,
        matcher,
        profile_name: str = "ultra_conservative",
        allow_conservative: bool = False,
    ) -> Dict[str, Any]:
        """Polls all 4 leagues concurrently using a single flat worker pool."""
        if time.time() - self.last_skew_sync > 300:
            self.sync_clock_skew()

        league_keys = list(LEAGUES.keys())
        results = {}

        with ThreadPoolExecutor(max_workers=len(league_keys)) as pool:
            future_to_league = {
                pool.submit(
                    self.discover_league_candidates,
                    l_key,
                    matcher,
                    profile_name=profile_name,
                    allow_conservative=allow_conservative,
                ): l_key
                for l_key in league_keys
            }
            for future in as_completed(future_to_league):
                l_key = future_to_league[future]
                try:
                    results[l_key] = future.result()
                except Exception as e:
                    results[l_key] = {"league": l_key, "rounds": {}, "candidates": [], "error": str(e)}

        total_candidates = sum(len(res.get("candidates", [])) for res in results.values())
        return {
            "leagues": results,
            "total_candidates": total_candidates,
            "server_epoch": self.get_server_epoch(),
            "active_protocol": self.active_protocol,
        }

    def close(self):
        try:
            self._client_h2.close()
            self._client_h1.close()
        except Exception:
            pass
