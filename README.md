# BtcTurk LLM Trading Agent

An autonomous, LLM-assisted spot trading bot for the BtcTurk exchange. It runs on a
fixed schedule, scans the market for momentum-with-pullback setups, asks an LLM
whether a candidate is worth entering, and manages exits with hard-coded risk rules.

Built as a small, disposable-capital experiment in combining rule-based risk
management with an LLM as a single, narrowly-scoped decision maker — not a
guaranteed-returns product.

## Features

- **Momentum + pullback screening** — filters the full BtcTurk ticker list for
  pairs that are up on the day but have pulled back from their daily high (avoids
  chasing the exact top).
- **LLM entry decisions, rule-based exits** — an LLM (via Groq's free tier) only
  decides *whether* to buy and picks stop-loss/take-profit percentages within
  fixed bounds; it never controls position sizing or exit execution. Exits are
  monitored and triggered by plain price comparisons.
- **Market context for the LLM** — Fear & Greed Index and general crypto news
  headlines (optional) are passed alongside candidates, without following any
  single account's posts.
- **Self-correcting memory** — every closed position is written to a "lessons"
  log in plain language; the last N lessons are fed back into the next LLM
  prompt so the model can avoid repeating past mistakes.
- **Portfolio-based position sizing** — position size is a percentage of total
  portfolio value (idle cash + open positions at current price), not just idle
  cash, so the bot doesn't automatically re-deploy 100% of capital after every
  exit. A minimum cash buffer is always preserved.
- **Fee/tax-aware PnL** — actual trade fills (not order parameters) are used to
  compute settlement amounts, so realized PnL reflects BtcTurk's real commission
  and tax deductions rather than a naive price delta.
- **Daily loss circuit breaker** — trading stops for the day once realized losses
  exceed a configurable percentage of the base capital.
- **Dry-run mode** — the entire decision/exit loop can run against live market
  data without ever placing a real order, for safe testing before going live.
- **Email reporting** — optional status emails (open positions, recent trades,
  all-time win rate) via Resend, and trade/exit notifications as they happen.

## Architecture

```
main.py            Single "tick": check open positions for stop/target, then
                    look for a new entry if capital is idle. Meant to be run
                    periodically (cron).
strategy.py         Candidate screening (momentum + pullback filter).
decision.py         LLM prompt + call (Groq). Returns buy/hold + stop/target %.
risk.py             Position sizing, exit price bounds, daily loss limit —
                    all enforced in code, independent of the LLM.
btcturk_client.py   Minimal BtcTurk Pro REST client (ticker, balances, market
                    orders, trade fills, HMAC request signing).
market_data.py      Fear & Greed index + optional news headlines.
storage.py          Flat JSON/JSONL persistence for positions, trade log,
                    decision log, and the "lessons" memory.
notify.py           Email notifications via the Resend API.
report.py           Periodic status report (balance, open positions, recent
                    trades, all-time PnL summary) sent by email.
```

## How it works

On each run:

1. If a position is open, check whether price has hit its stop-loss or
   take-profit level; if so, exit and record the outcome (including a plain-
   language "lesson").
2. If no position is open (or capital remains), screen all TRY pairs for
   candidates, gather Fear & Greed + news context and recent lessons, and ask
   the LLM for a buy/hold decision.
3. On a "buy" decision, size the position from total portfolio value (bounded
   by available cash and the minimum cash buffer), place a market order, and
   record entry cost and exit levels.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your own API keys
python main.py         # single tick; schedule with cron for periodic runs
```

Run `report.py` on a separate schedule (e.g. daily) for a summary email.

**Safety note:** when creating the BtcTurk API key, grant **only** the "Trade"
permission and keep "Withdrawal" disabled — the bot can then never move funds
out of the exchange, only trade within the account.

## Tech stack

- Python 3.11+
- [BtcTurk Pro API](https://github.com/BTCTrader/broker-api-docs) — market data
  and order execution
- [Groq](https://groq.com/) — free-tier LLM inference for entry decisions
- [Resend](https://resend.com/) — transactional email for notifications/reports
- Flat JSON/JSONL files for state and logs (no database dependency)

## Known limitations

- The momentum/pullback filter is a simple high/low ratio heuristic, not a full
  OHLC breakout/retest analysis.
- Only one position at a time is opened per scan (no multi-asset diversification
  logic beyond what the daily loop naturally allows).
- If the LLM provider's free-tier rate limit is hit, that tick is skipped and
  retried on the next scheduled run.
