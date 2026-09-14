import os, sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from engine.ticket_builder import calculate_stake, quantize_to_human_step, TicketBuilder

def test_staking_quantization():
    print("[*] Testing Staking Quantization...")
    # Test values around steps
    assert quantize_to_human_step(9.5) == 10.0
    assert quantize_to_human_step(12.0) == 10.0
    assert quantize_to_human_step(14.0) == 15.0
    assert quantize_to_human_step(22.0) == 20.0
    assert quantize_to_human_step(24.0) == 25.0
    assert quantize_to_human_step(48.0) == 50.0
    assert quantize_to_human_step(98.0) == 100.0
    print("[+] All quantizer checks passed!")

def test_balance_scaling():
    print("[*] Testing Balance Tier Scaling...")
    # Low balance (₦600) -> 5% is ₦30
    s_600 = calculate_stake(600.0, "single", 0.05)
    print(f"  Balance ₦600  -> Single Stake: ₦{s_600}")
    assert s_600 in [30.0, 35.0]

    # Mid balance (₦2,500) -> 5% is ₦125
    s_2500 = calculate_stake(2500.0, "single", 0.05)
    print(f"  Balance ₦2,500 -> Single Stake: ₦{s_2500}")
    assert s_2500 in [125.0, 150.0]

    # High balance (₦10,000) -> 5% is ₦500
    s_10000 = calculate_stake(10000.0, "single", 0.05)
    print(f"  Balance ₦10,000 -> Single Stake: ₦{s_10000}")
    assert s_10000 == 500.0
    print("[+] Balance tier scaling verified!")

def test_ticket_builder_no_collision():
    print("[*] Testing Ticket Construction Collision Guard...")
    builder = TicketBuilder()
    mock_edges = [
        {"match_name": "LIV - CHE", "outcome": "1x2_1_val", "raw_odds": 2.10, "min_edge": 0.08},
        {"match_name": "LIV - CHE", "outcome": "double_chance_1x_val", "raw_odds": 1.35, "min_edge": 0.06}, # Collision
        {"match_name": "ARS - TOT", "outcome": "o_u_2_5_ov_val", "raw_odds": 1.85, "min_edge": 0.07},
        {"match_name": "MCI - MUN", "outcome": "gg_ng_gg_val", "raw_odds": 1.95, "min_edge": 0.05},
    ]

    tickets = builder.build_tickets(mock_edges, balance=800.0, max_tickets=3)
    print(f"[+] Built {len(tickets)} tickets:")
    for t in tickets:
        matches = [leg["match_name"] for leg in t["legs"]]
        print(f"  - Type: {t['type']} | Matches: {matches} | Stake: ₦{t['stake']}")
        # Ensure no duplicate matches within a single ticket
        assert len(matches) == len(set(matches)), "Collision detected in ticket legs!"

    print("[+] All collision guard checks passed!")

if __name__ == "__main__":
    test_staking_quantization()
    test_balance_scaling()
    test_ticket_builder_no_collision()
