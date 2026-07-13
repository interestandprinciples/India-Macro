"""
Theme taxonomy for RBI macro indicators.

Each series gets exactly one theme based on keyword matching against the
column name (case-insensitive). Order of rules matters — the first match wins.

Themes (and the rough ordering used in the dashboard tabs):
  monetary      — Policy Repo, MSF, SDF, Bank Rate, Base Rate, Reverse Repo,
                  T-Bill & G-Sec yields, CRR, SLR, Forward Premia
  rates_market  — Overnight Repo/Reverse Repo, Call Money (Borrowings)
  money_banking — M0/M1/M2/M3, credit, deposits, RBI balance sheet, CP/CD
                  outstanding, credit-deposit ratios
  inflation     — CPI (any base), WPI, Food CPI, CPI-AL/RL/IW
  currency      — INR/USD reference, month-end, RBI reference rate
  trade         — Foreign trade exports, imports, balance
  bop           — Balance of Payments, current/capital account, services,
                  transfers, monetary movements, FDI/FPI
  reserves_debt — FX Reserves, FCA, External Debt, Overall BoP Net
  gov_finance   — Fiscal Deficit, Revenue, Expenditure, Market Borrowing
  economy       — IIP, GDP, GFCF, PFCE, GFCE, House Price Index, Money
                  Supply components beyond M3
  markets       — NIFTY, BANKEX
  payments      — Retail Payments, Digital Payments
  other         — fallback
"""
from __future__ import annotations
import re


THEME_ORDER = [
    "monetary",
    "rates_market",
    "money_banking",
    "inflation",
    "currency",
    "trade",
    "bop",
    "reserves_debt",
    "gov_finance",
    "economy",
    "markets",
    "payments",
    "other",
]

THEME_META = {
    "monetary":      {"label": "Monetary Policy & Rates",  "icon": "🏦", "color": "#ff9933"},
    "rates_market":  {"label": "Money Market Rates",       "icon": "📈", "color": "#fbbf24"},
    "money_banking": {"label": "Money & Banking",          "icon": "🏛️", "color": "#60a5fa"},
    "inflation":     {"label": "Inflation & Prices",       "icon": "🔥", "color": "#f87171"},
    "currency":      {"label": "Currency & FX",            "icon": "💱", "color": "#a78bfa"},
    "trade":         {"label": "Foreign Trade",            "icon": "🚢", "color": "#22d3ee"},
    "bop":           {"label": "BoP & Capital Flows",      "icon": "🌐", "color": "#34d399"},
    "reserves_debt": {"label": "Reserves & External Debt", "icon": "💰", "color": "#4ade80"},
    "gov_finance":   {"label": "Government Finances",      "icon": "🏛",  "color": "#f472b6"},
    "economy":       {"label": "Economy & Industry",       "icon": "🏭", "color": "#818cf8"},
    "markets":       {"label": "Equity Markets",           "icon": "📊", "color": "#fb7185"},
    "payments":      {"label": "Payments",                 "icon": "💳", "color": "#06b6d4"},
    "other":         {"label": "Other",                    "icon": "•",   "color": "#8693ab"},
}

# Each rule is (theme, [keywords...]); the first matching theme wins.
RULES = [
    # ---- Monetary Policy & Rates ----
    ("monetary", [
        r"\brepo rate\b", r"reverse repo", r"\bmsf\b", r"marginal standing",
        r"bank rate", r"base rate", r"\bsdf\b", r"standing deposit",
        r"forward premia", r"treasury bill", r"\bg-?sec\b", r"10[\s\-]?year",
        r"cash reserve ratio", r"\bcrr\b", r"statutory liquidity",
        r"\bslr\b", r"policy repo",
    ]),
    # ---- Money market rates (overnight) ----
    ("rates_market", [
        r"call money", r"overnight", r"borrowings.*high|borrowings.*low",
    ]),
    # ---- Money & Banking ----
    ("money_banking", [
        r"\bm[0-3]\b", r"money supply", r"broad money", r"narrow money",
        r"non food credit", r"aggregate deposit", r"aggregate desposit",
        r"bank credit", r"food credit",
        r"cash[\s\-]?deposit ratio", r"credit[\s\-]?deposit ratio",
        r"credit to the commercial", r"credit to the government",
        r"commercial paper", r"certificates of deposit",
        r"rbi balance sheet", r"currency with the public",
        r"demand deposit", r"other deposits with reserve",
        r"deployment of bank credit", r"personal loan", r"\bhousing\b",
        r"investment in india",
    ]),
    # ---- Inflation ----
    ("inflation", [
        r"consumer price index", r"\bcpi\b", r"wholesale price",
        r"\bwpi\b", r"agricultural labourer", r"rural labourer",
        r"industrial worker", r"food and beverage",
        r"all india.*consumer price", r"food.*beverage",
    ]),
    # ---- Currency / FX ----
    ("currency", [
        r"inr per usd", r"per us dollar", r"per us\$",
        r"rupees vis", r"exchange rate of indian rupee",
    ]),
    # ---- Foreign Trade ----
    ("trade", [
        r"foreign trade export", r"foreign trade import",
        r"foreign trade balance", r"trade balance total",
    ]),
    # ---- BoP & Capital Flows ----
    ("bop", [
        r"\bbop\b", r"balance of payments", r"current account",
        r"capital account", r"merchandise", r"\bservices\b",
        r"transfer\s+(?:official|private)", r"errors and omissions",
        r"monetary movements", r"foreign direct investment",
        r"\bfdi\b", r"portfolio (?:investment|foreign)",
        r"direct investment", r"net portfolio",
        r"net foreign direct", r"total investment inflows",
        r"fcnr", r"external commercial borrowing",
    ]),
    # ---- Reserves & External Debt ----
    ("reserves_debt", [
        r"foreign exchange reserve", r"foreign currency asset",
        r"\bfca\b", r"external debt", r"international investment position",
    ]),
    # ---- Government Finances ----
    ("gov_finance", [
        r"fiscal deficit", r"primary deficit", r"interest payment",
        r"total revenue", r"total expenditure",
        r"market borrowing", r"sg gross",
    ]),
    # ---- Economy & Industry ----
    ("economy", [
        r"industrial production", r"\biip\b",
        r"gdp at market", r"gross domestic product",
        r"gross fixed capital", r"private final consumption",
        r"government final consumption", r"change in stock",
        r"house price index", r"export.*constant|export.*current",
        r"less import|import.*constant|import.*current",
    ]),
    # ---- Equity Markets ----
    ("markets", [
        r"\bnifty\b", r"cnx nifty", r"s&p cnx",
        r"\bbse\b", r"bankex", r"market capit",
    ]),
    # ---- Payments ----
    ("payments", [
        r"retail payment", r"digital payment", r"upi",
    ]),
]


def classify(name: str) -> str:
    """Return the theme id for a series name (case-insensitive)."""
    if not name:
        return "other"
    n = name.lower()
    for theme, patterns in RULES:
        for pat in patterns:
            if re.search(pat, n):
                return theme
    return "other"


def get_meta(theme_id: str) -> dict:
    return THEME_META.get(theme_id, THEME_META["other"])