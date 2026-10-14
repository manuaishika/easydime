import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import details


def T(*rows):
    return [[(c, None) for c in r] for r in rows]


# Shapes copied from a real IPO page (SRIT India), as printed by the live probe.
SRIT = [
    T(["Period Ended", "Revenue", "Expense", "PAT", "Assets"], ["2024", "₹282.22", "₹243.88", "₹29.08", "₹428.96"],
      ["2025", "₹400.50", "₹354.31", "₹33.60", "₹496.64"], ["2026", "₹462.54", "₹407.59", "₹43.29", "₹614.16"]),
    T(["Name of the Company", "Face Value (₹)", "EPS basic (₹)", "EPS Diluted (₹)", "RONW (%)", "P/E Ratio", "NAV (₹)"],
      ["Powerica Limited", "5", "15.26", "15.26", "15.37 %", "24.45", "99.76"], ["Listed Peers"],
      ["Cummins India Limited", "2", "72.15", "72.15", "26.45%", "64.13", "272.78"],
      ["Kirloskar Oil Engines Limited", "2", "33.71", "33.60", "15.85%", "43.24", "212.60"]),
    T(["IPO Open Date", "September 28, 2026"], ["IPO Close Date", "September 30, 2026"], ["IPO Price Band", "₹123 to ₹130 Per Share"],
      ["Issue Size", "Approx ₹218.40 Crores"], ["Fresh Issue", "Approx ₹218.40 Crores"], ["IPO Listing", "BSE, NSE"]),
    T(["Application", "Lot Size", "Shares", "Amount"], ["Retail Minimum", "1", "115", "₹14,950"],
      ["Retail Maximum", "13", "1495", "₹1,94,350"]),
    T(["Investor Category", "Share Offered", "-% Shares"], ["Anchor Investor", "50,40,000 Shares", "30%"],
      ["QIB (Ex. Anchor)", "33,60,000 Shares", "20%"], ["NII Shares Offered", "25,20,000 Shares", "15%"],
      ["Retail Shares Offered", "58,80,000 Shares", "35%"]),
    T(["IPO Open Date:", "September 28, 2026"], ["Basis of Allotment:", "October 1, 2026"], ["Refunds:", "October 5, 2026"],
      ["IPO Listing Date:", "October 6, 2026"]),
    T(["Particular", "Pre IPO Shares", "Pre IPO % Shares", "Post IPO Shares", "Post IPO % Shares"],
      ["Promoter and Promoter Group", "–", "-%", "–", "-%"]),
    T(["Purpose", "Crores"], ["Funding of capital expenditure requirements", "₹15.36"],
      ["Funding working capital requirements of the company", "₹124.00"], ["General Corporate Purposes", "₹-"]),
    T(["KPI", "Values"], ["ROE:", "30.23%"], ["ROCE:", "28.79%"], ["EBITDA Margin:", "14.39%"], ["PAT Margin:", "9.62%"],
      ["Debt to equity ratio:", "0.23"], ["Earning Per Share (EPS):", "₹9.47 (Basic)"], ["Price/Earning P/E Ratio:", "N/A"],
      ["Net Asset Value (NAV):", "₹40.71"]),
]


def test_num():
    assert details.num("₹14,950") == 14950 and details.num("15.37 %") == 15.37 and details.num("-₹3.2") == -3.2
    assert all(details.num(x) is None for x in ("₹-", "–", "-%", "N/A", "", None))


def test_parse_real_shape():
    d = details.parse_tables(SRIT)
    assert d["lot"] == {"lots": 1, "shares": 115, "amount": 14950}
    assert d["categories"]["retail"] == {"shares": 5880000, "pct": 35}
    assert [f["revenue"] for f in d["financials"]] == [282.22, 400.5, 462.54]
    assert [p["pe"] for p in d["peers"]] == [24.45, 64.13, 43.24]          # sub-heading row skipped
    assert d["kpi"]["eps"] == 9.47 and d["kpi"]["roe"] == 30.23 and "pe" not in d["kpi"]
    assert d["dates"] == {"allotment": "2026-10-01", "refund": "2026-10-05", "listing": "2026-10-06"}
    assert d["promoter"] == {"pre": None, "post": None}
    assert d["purposes"][2]["crore"] is None


def test_analysis_numbers():
    d = details.parse_tables(SRIT)
    i = dict(name="SRIT", price=130.0, gmp=31.0, gain=23.85, sme=False)
    a = details.analyse(i, d, date(2026, 9, 30), date(2026, 10, 1))
    app = dict(a["sections"][0][1])
    assert app["Minimum application"] == "1 lot = 115 shares = ₹14,950"
    assert app["Profit/loss if it lists at today's GMP"].startswith("+₹3,565")        # 115 × 31
    assert app["Money blocked"].startswith("5 days")                                  # 30 Sep -> 5 Oct refund
    fd = 14950 * 0.07 * 5 / 365
    assert f"₹{fd:,.2f}" in dict(a["sections"][0][1])[f"Same money in a 7% fixed deposit"]
    assert [round(s[1]) for s in a["scenarios"]] == [3565, 1782, 0, round(115 * -13)]
    assert a["odds"][1] == (5, 0.2, 3565 / 5)
    val = dict(next(s for s in a["sections"] if s[0] == "Valuation")[1])
    assert val["Price ÷ earnings at the issue price"].startswith("13.7×")             # 130 / 9.47
    assert val["Listed peers' median P/E"].startswith("43.2×") and "discount" in val["Valuation vs peers"]
    assert a["quality"] == "Strong" and "agree" in a["bottom"]
    assert any("Revenue growing" in p for p in a["positives"])


def test_analysis_without_details():
    a = details.analyse(dict(name="X", price=100.0, gmp=5.0, gain=5.0, sme=True), None, date(2026, 10, 5), date(2026, 10, 1))
    assert not a["has_details"] and a["quality"] is None and a["scenarios"] == []
    assert any(f.startswith("SME issue") for f in a["flags"])


def test_page_for_a_different_ipo_is_rejected():
    d = details.parse_tables(SRIT)                     # lot is ₹14,950 for 115 shares => issue price ₹130
    assert details.matches(dict(price=130.0), d)
    assert not details.matches(dict(price=72.0), d)    # e.g. Papadmalji Agro linked to Black Opal's page
    a = details.analyse(dict(name="X", price=72.0, gmp=0.0, gain=0.0, sme=True), d, date(2026, 10, 1), date(2026, 9, 30))
    assert not a["has_details"] and a["quality"] is None     # wrong company's numbers are never used


def test_wording_and_quality():
    d = details.parse_tables(SRIT)
    a = details.analyse(dict(name="S", price=130.0, gmp=31.0, gain=23.85, sme=False), d, date(2026, 9, 30), date(2026, 9, 29))
    app = dict(a["sections"][0][1])
    assert app["Minimum application"].startswith("1 lot =")          # singular
    assert "not repeatable" in app["Return if GMP holds, annualised"]
    d2 = details.parse_tables(SRIT)
    d2["lot"] = {"lots": 2.0, "shares": 230.0, "amount": 29900.0}
    a2 = details.analyse(dict(name="S", price=130.0, gmp=31.0, gain=23.85, sme=True), d2, date(2026, 9, 30), date(2026, 9, 29))
    assert dict(a2["sections"][0][1])["Minimum application"].startswith("2 lots =")
    d["peers"] = d["peers"][:1]
    v = dict(next(s for s in details.analyse(dict(name="S", price=130.0, gmp=31.0, gain=23.85, sme=False), d, date(2026, 9, 30),
                                             date(2026, 9, 29))["sections"] if s[0] == "Valuation")[1])
    assert "Listed peer's P/E" in v and v["Listed peer's P/E"].endswith("(1 peer)")


# Shapes copied from the live probe of IPO Watch's subscription page and a GMP page.
SUBS = [T(["IPO", "Type", "Closing Date", "QIB (X)", "NII (X)", "Retail (X)", "Total (X)", "Last Updated"],
          ["Fusion CX", "Mainboard", "October 16, 2026", "0.00", "0.48", "1.64", "0.43", "17:41"],
          ["Ravita Engineering", "SME", "October 16, 2026", "1.05", "1.69", "0.95", "1.14", "17:41"],
          ["HD Fire Protect", "Mainboard", "October 15, 2026", "1.49", "48.74", "11.39", "16.53", "17:41"])]
GMPDAYS = [T(["Date", "IPO GMP", "GMP Trend", "Gain", "Last Updated"], ["14 October", "₹-", "🟡", "-%", "17:06"],
             ["13 October", "₹5", "🟢", "4.50%", "17:29"], ["12 October", "₹3", "🟢", "2.70%", "18:02"])]


def test_parse_subscriptions():
    rows = details.parse_subscriptions(SUBS)
    assert [r["name"] for r in rows] == ["Fusion CX", "Ravita Engineering", "HD Fire Protect"]
    hd = rows[2]
    assert (hd["qib"], hd["nii"], hd["retail"], hd["total"], hd["updated"]) == (1.49, 48.74, 11.39, 16.53, "17:41")
    assert details.parse_subscriptions(SRIT) == []                       # other tables are ignored


def test_parse_gmp_days_skips_blank_days_and_sorts():
    days = details.parse_gmp_days(GMPDAYS, date(2026, 10, 14))
    assert days == [("2026-10-12", 3.0, "18:02"), ("2026-10-13", 5.0, "17:29")]      # "₹-" day dropped
    dec = details.parse_gmp_days([T(["Date", "IPO GMP", "x", "y", "Last Updated"], ["30 December", "₹9", "", "", "10:00"])], date(2027, 1, 2))
    assert dec == [("2026-12-30", 9.0, "10:00")]                                       # December seen in January = last year


def test_live_subscription_drives_allotment_odds():
    d = details.parse_tables(SRIT)
    i = dict(name="S", price=130.0, gmp=31.0, gain=23.85, sme=False)
    a = details.analyse(i, d, date(2026, 9, 30), date(2026, 9, 29), {"retail": 4.0, "total": 12.5, "qib": 1, "nii": 1})
    sec = dict(next(s for s in a["sections"] if s[0].startswith("Allotment odds (live"))[1])
    assert sec["Retail subscription so far"] == "4×" and sec["Chance of getting a one-lot allotment"].startswith("25%")
    assert sec["Expected profit per application at today's GMP"] == "+₹891"           # 115 × 31 × 25%
    assert any("Strong demand" in p for p in a["positives"])
    under = details.analyse(i, d, date(2026, 9, 30), date(2026, 9, 29), {"retail": 0.5, "total": 0.6})
    assert dict(next(s for s in under["sections"] if s[0].startswith("Allotment odds (live"))[1])["Chance of getting a one-lot allotment"].startswith("100%")
    last_day = details.analyse(i, d, date(2026, 9, 30), date(2026, 9, 30), {"retail": 0.5, "total": 0.6})
    assert any("not fully subscribed" in f for f in last_day["flags"])
