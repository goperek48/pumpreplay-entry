"""Pump.fun replay paper bot: buy the slow starters, sell fast, pyramid the runners.

What the tape actually does: a new pump.fun coin is born on its bonding
curve and the crowd renders its verdict within minutes. Across the
house dev window (one day, 1,222 fresh coins) the typical coin spiked
about 30% over its birth price inside four minutes, a quarter of them
doubled or better, and barely one in twenty-five was still up a quarter
by the end of the day. The money is made in the spike, not the hold:
anything left sitting reverts to where it started.

So the bot only ever buys a coin while its first pump is still small.
By the time the size cap (1% of real reserves) first allows a real
buy, the fast coins have already run 40-70% and are spent; the slow
ones are up just 8-10% and still have room. On the dev window the slow
group won about half of its races to +50% before -20%, while the fast
group won barely a fifth. The bot therefore buys at the first batch
where the cap reaches the 0.01 SOL round-trip minimum and the price is
no more than 10% above birth, one buy per coin, staking the cap up to
0.10 SOL. A coin that blows past the ceiling gets no chase; it may
still be bought on a pullback inside the entry window.

Once in, the bot is impatient. It sells everything at +25%, or at
-20%, or when the price slips 10% off its best print since entry, or
after 300 slots (about two minutes) no matter what. Winners get one
pyramid add: if a position is up 20% and the cap has grown to allow a
0.03 SOL add-on, the bot adds up to 0.10 SOL, blending the entry price
across the two stakes. The extra size goes only to coins already in
profit, and a larger order spreads the flat per-order chain fee over
more lamports. The house closes completed curves and flattens the book
at the end of the window by itself.

Limits the bot never crosses: five open positions, sixteen orders a
batch, never spending cash it does not have after fees, and every order
carries a 500 bps slippage bound. No clock, no environment, no
unseeded dice: feed it the same tape twice and it answers byte for
byte the same way.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bot  # noqa: E402  (after the sys.path line: -P leaves the script dir off sys.path)

# --- strategy knobs (kept together so a sweep can retune them) ---
ENTRY_MULT = 1.00          # buy once the price is at least the birth price
ENTRY_MAX_MULT = 1.10      # ... but only while the opening run is still young:
                           # a coin already 40% past birth when the size cap
                           # first allows a buy is running on fumes (the dev
                           # window gives that group a ~20% win rate), while
                           # the gentle starters near +8-10% win about half
                           # of their races to +50% before -20%
ENTRY_WINDOW_SLOTS = 1200  # ... and the coin is no more than ~8 min old
ENTRY_MIN_TRADES = 0       # ... with at least this many trades on the tape
MIN_STAKE_LAMPORTS = 10_000_000        # 0.01 SOL: the guardrail round-trip floor
MAX_STAKE_LAMPORTS = 100_000_000       # 0.10 SOL: the largest single stake
TAKE_PROFIT_MULT = 1.25    # bank the whole position at +25% over entry
STOP_LOSS_MULT = 0.80      # dump the whole position at -20% under entry
TRAIL_MULT = 0.90          # dump it when the price sags 10% off its peak
MAX_HOLD_SLOTS = 300       # hard clock: out after ~2 minutes regardless
# --- scale-in: add size only to the coins already proving themselves ---
SCALE_IN_MULT = 1.20       # add once the position is +20% over entry
SCALE_IN_MIN_CAP = 30_000_000   # ... and the cap has grown to allow a real add
SCALE_IN_MAX_LAMPORTS = 100_000_000  # never add more than 0.10 SOL to one coin
MAX_SLIPPAGE_BPS = 500     # a fill may land at most 5% worse than the quote


class Position:
    """One live trade, as the bot remembers it."""

    __slots__ = ("entry_price", "peak_price", "entry_slot", "stake", "scaled_in")

    def __init__(self, entry_price, entry_slot, stake):
        self.entry_price = entry_price
        self.peak_price = entry_price
        self.entry_slot = entry_slot
        self.stake = stake          # lamports the first buy cost
        self.scaled_in = False      # the one pyramid add is still unused


class Bot:
    """Buys each slow starter once, exits fast, never holds more than five."""

    def __init__(self):
        # mint -> price at birth (quote per token on the CreateEvent)
        self.birth = {}
        # mint -> trades printed on the curve so far
        self.trades_seen = {}
        # mint -> slot its CreateEvent landed in
        self.born_slot = {}
        # mints bought once already (a dumped coin gets no second entry)
        self.bought = set()
        # mint -> Position for the trades still open
        self.open = {}

    def on_batch(self, state, batch):
        # Note the batch's events on the per-coin tape, then decide.
        for e in batch["events"]:
            mint = e["mint"]
            kind = e["event"]
            if kind == "CreateEvent":
                # Take the birth price from the event itself: the curve
                # in state already includes every trade in this batch,
                # so reading it here would price the birth after the
                # first trades of the same slot, not at creation.
                vt = int(e.get("virtual_token_reserves") or 0)
                vq = int(e.get("virtual_quote_reserves") or 0)
                if vt > 0 and vq > 0:
                    self.birth[mint] = vq / vt
                    self.born_slot[mint] = e["slot"]
                    self.trades_seen[mint] = 0
            elif kind == "TradeEvent":
                if mint in self.trades_seen:
                    self.trades_seen[mint] += 1
        orders = []
        orders.extend(self._exits(state))
        orders.extend(self._scale_ins(state, batch))
        orders.extend(self._entries(state, batch))
        return orders

    def _scale_ins(self, state, batch):
        """Add size to the winners, once each. The add goes out only when
        the coin has already shown it can run (+20%) and the cap has
        grown fat enough for a real add-on. The extra lamports ride only
        on coins already in the green, and a fatter order spreads the
        flat per-order chain fee over more lamports than the tiny first
        stake ever could."""
        orders = []
        caps = state.hello["caps"]
        tx = state.tx_fee_lamports()
        free = state.free_cash_lamports()
        for mint, pos in list(self.open.items()):
            if pos.scaled_in:
                continue
            if len(orders) + len(state.pending) >= caps["max_orders_per_batch"]:
                break
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                continue
            price = self._price(curve)
            if price is None or price < pos.entry_price * SCALE_IN_MULT:
                continue
            cap = state.max_buy_lamports(mint)
            if cap < SCALE_IN_MIN_CAP:
                continue
            add = min(cap, SCALE_IN_MAX_LAMPORTS)
            if free < add + tx:
                continue
            orders.append(
                {
                    "side": "buy",
                    "mint": mint,
                    "quote_lamports": add,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
            )
            # Average the entry price across both stakes, so the exit
            # rules keep measuring the full position against what it
            # really cost.
            pos.entry_price = (
                pos.entry_price * pos.stake + price * add
            ) / (pos.stake + add)
            pos.stake += add
            pos.scaled_in = True
            free -= add + tx
        return orders

    def _exits(self, state):
        """Close out every open trade whose exit rule has tripped."""
        orders = []
        for mint, pos in list(self.open.items()):
            holding = state.positions.get(mint)
            if holding is None or holding.token_amount <= 0:
                # Nothing left to sell (already closed by the house or
                # sold): drop it from the book.
                del self.open[mint]
                continue
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                # A finished curve refuses sell orders and the house
                # closes it on its own. Drop it from the book.
                if curve is not None and curve.complete:
                    del self.open[mint]
                continue
            price = self._price(curve)
            if price is None:
                continue
            if price > pos.peak_price:
                pos.peak_price = price
            if (
                price >= pos.entry_price * TAKE_PROFIT_MULT
                or price <= pos.entry_price * STOP_LOSS_MULT
                or price <= pos.peak_price * TRAIL_MULT
                or state.slot - pos.entry_slot >= MAX_HOLD_SLOTS
            ):
                orders.append(self._sell(mint, holding.token_amount))
                del self.open[mint]
        return orders

    @staticmethod
    def _sell(mint, token_amount):
        return {
            "side": "sell",
            "mint": mint,
            "token_amount": token_amount,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }

    def _entries(self, state, batch):
        """First buys on fresh coins whose opening run is still gentle."""
        orders = []
        caps = state.hello["caps"]
        tx = state.tx_fee_lamports()
        free = state.free_cash_lamports()
        slots = caps["max_open_positions"] - state.committed_position_count()
        if slots <= 0:
            return orders
        for e in batch["events"]:
            if len(orders) + len(state.pending) >= caps["max_orders_per_batch"]:
                break
            mint = e["mint"]
            if mint in self.bought or mint in self.open:
                continue
            if mint not in self.birth:
                continue
            if self.trades_seen.get(mint, 0) < ENTRY_MIN_TRADES:
                continue
            if state.slot - self.born_slot.get(mint, state.slot) > ENTRY_WINDOW_SLOTS:
                continue
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                continue
            price = self._price(curve)
            if price is None or price < self.birth[mint] * ENTRY_MULT:
                continue
            if price > self.birth[mint] * ENTRY_MAX_MULT:
                # Run too far already: the move is spent. Hold off and
                # wait for a dip back inside the window instead of
                # chasing the top.
                continue
            cap = state.max_buy_lamports(mint)
            if cap < MIN_STAKE_LAMPORTS:
                continue
            stake = min(cap, MAX_STAKE_LAMPORTS)
            if slots <= 0 or free < stake + tx:
                continue
            orders.append(
                {
                    "side": "buy",
                    "mint": mint,
                    "quote_lamports": stake,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
            )
            self.bought.add(mint)
            self.open[mint] = Position(price, state.slot, stake)
            free -= stake + tx
            slots -= 1
        return orders

    @staticmethod
    def _price(curve):
        """A curve's current price in quote lamports per token, or None."""
        if curve.virtual_token_reserves <= 0:
            return None
        return curve.virtual_quote_reserves / curve.virtual_token_reserves


def main():
    bot = Bot()
    makefun_bot.run(bot.on_batch)


if __name__ == "__main__":
    main()
