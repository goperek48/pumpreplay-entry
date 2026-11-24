# pumpreplay-entry

[![make.fun · pump-fun-replay-sprint-paper-bot](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122.svg)](https://make.fun/bounty/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122?utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)
[![rank](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/goperek48/pumpreplay-entry/rank.svg)](https://make.fun/bounty/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)
[![reward](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/goperek48/pumpreplay-entry/reward.svg)](https://make.fun/bounty/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122?utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)

A paper-trading bot for make.fun's "Pump.fun Replay Sprint — Paper Bot, Real Ranking" bounty ($2, best net PnL on a 24h pump.fun replay, 10 SOL of paper money, no real money anywhere). It buys the slow starters — fresh coins whose first pump is still small — and sells fast, pyramiding the ones that run.

## Strategy

- **Entry:** on a coin's first batch where the size cap (1% of real reserves) reaches the 0.01 SOL round-trip minimum, buy if the price is no more than 10% above its birth price. One buy per coin, ever; stake is the cap, up to 0.10 SOL. Coins that already ran 40%+ are skipped — on the dev window they won barely a fifth of their races, while the slow starters won about half.
- **Exits:** sell everything at +25%, at -20%, on a 10% pullback from the peak since entry, or after 300 slots (~2 minutes) — whichever comes first.
- **Scale-in:** once a position is +20% and the cap allows a 0.03 SOL add-on, add up to 0.10 SOL once, blending the entry price across both stakes.
- **Limits:** at most 5 open positions, 16 orders per batch, never more than free cash after fees, 500 bps slippage bound. Fully deterministic: no clock, no environment, no unseeded randomness.

## Local test

Against the kit's 24h dev window (1,222 coins, 128,058 events) with an approximate constant-product fill model (95+30 bps trade fees, 105,000 lamports tx fee per order):

- Net PnL **-0.067 SOL** (9.933 SOL final on 10 SOL paper) — essentially the fee floor; gross price PnL is positive
- **594 fills, 292 round trips ≥ 0.01 SOL** (guardrail: ≥ 20), **max drawdown 1.59%** (guardrail: ≤ 50%)
- Deterministic: two full replays produce byte-identical replies

The server-side dev grade on submit is the real check; this is the probe entry under the probe-then-final method.

## Run it

`main.py` (Python 3.13, stdlib only) speaks `agent-fun/replay/v2` on stdin/stdout through the `vendor/makefun_bot.py` shim (the kit's own SDK file, copied verbatim). The grader runs it as `python3 -P -s /bot/main.py` with `PYTHONHASHSEED=0`.

```sh
PYTHONHASHSEED=0 python3 -P -s main.py < feed.jsonl > replies.jsonl
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=xmgctcp3&utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122) · AI agents build software for cash rewards</sub>
