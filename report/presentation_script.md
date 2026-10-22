# Presentation script

Spoken script for the Calibrum deck, one block per slide, in deck order. Target length: about 38 minutes. Times are
per slide; the running total is at the end of each section. Numbers match the slides and the report chapters.

## Introduction (about 3.5 minutes)

### 1. Calibrum (cover) · 0:30

Good morning. My name is Phan Quoc Vien. Today I will present Calibrum, a trading strategy for VN30 index futures on
30-minute bars. It combines three small trading ideas into one position. I developed it following steps 1 to 6 of the
ALGOTRADE 9-step process, and I will walk through the steps in that order.

### 2. VN30F1M: leveraged, retail-heavy, cash settled · 1:00

First, the market. I trade the front-month contract on the VN30 index, the thirty largest stocks on HOSE. One index
point is worth 100,000 dong per contract. Trading runs from 9 to 14:45 with a lunch break, and the last fifteen minutes
are a closing auction. The contract expires on the third Thursday of the month and is settled in cash against the
index. Costs are the HNX and VSDC fees and the tax on transfers.

The last box is what makes this market move the way it does. The initial margin is 17 percent, so one dong of capital
controls about six dong of index exposure. Most of the traders are individuals. Leveraged retail money reacts fast and
in the same direction, and two of my three ideas, momentum and the basis, feed on that.

### 3. Why combine several sources of alpha · 1:00

A good trading algorithm combines several sources of alpha. Every source has periods when it works well and periods
when it does not. If the sources rest on different mechanisms, the weak stretches of one tend to fall in the good
stretches of another, so the combination earns more steadily. ALGOTRADE makes the same point in its article on capital
allocation: uncorrelated strategies raise the Sharpe ratio and shorten the recovery after a drawdown.

Calibrum applies that principle with three sources: the calendar, the basis and momentum. The question of this work is:
does the combination hold up out of sample, after real costs? To answer it I use two engines. A fast lab engine tests
the alpha alone. The Plutus exchange simulator tests alpha plus execution, with real contracts, real fees and margin.

### 4. The 9-step process: steps 1 to 6 covered today · 0:45

This is the roadmap. The filled cards are the six steps I cover today: hypotheses, data, rules, in-sample test,
optimization and out-of-sample test. Step 7, paper trading, is already running on the exchange's paper platform since
the 25th of August; its results are not part of today's talk. The dashed cards, small account testing and real trading,
come after that.

Running total: 3:15

## Step 1: Forming algorithm hypotheses (about 6 minutes)

### 5. 01 Forming Algorithm Hypotheses (section) · 0:15

Step one: where the ideas come from.

### 6. Three ideas, three sources of alpha · 1:00

Each sleeve comes from a different route. Calendar comes from my own experience: two months of daily paper trading
from August 2026, plus calendar effects documented in other markets. Basis comes from watching the basis, the gap
between futures and the index. Momentum comes from the research literature. In the ALGOTRADE terms, these are three
different sources of alpha: trading experience and behavioral bias, mispricing and market structure, and statistical
modeling.

### 7. Some sessions force traders to act · 1:15

Calendar has two layers. The core legs are what I saw while paper trading. Mondays, when the market does not open
higher, tend to fall: bad news piles up over the weekend and brokers enforce margin calls early in the week, so some
traders are forced to sell. Tuesdays and Wednesdays tend to rise once that selling is done.

The auxiliary legs come from the literature. Turn of the month, from monthly inflows like salaries and fund
contributions. The session before a holiday, when short holders close before a long break. And expiry day, when the
futures discount has to close at cash settlement. Every leg answers the same question: who is forced to trade on that
day.

### 8. Calendar legs on in-sample data · 1:00

Here is the check on in-sample data. The two core legs are clear: the Monday leg loses 12 points on average, with a
permutation p-value of 0.003, and Tuesday and Wednesday also have p equal to 0.003. The auxiliary legs are another
story. Pre-holiday happens only about five times a year; I have seven cases in-sample. One by one, these legs are too
rare to prove. So I keep them because of the published evidence and the mechanism, not because of this table, and I
test them as one group in step 5.

### 9. Futures stray from the index, then return · 1:15

The Basis sleeve. The basis is futures minus the index. It is rarely zero: the median distance is 4.1 points, and only 13.7
percent of bars are within one point. It also shrinks toward expiry, from 6.5 points three weeks before to 3.6 points
in the last two days.

Why does it come back? The basis has a slow part, cost of carry and the general mood, and a fast part: leveraged retail
traders chase and dump the contract faster than thirty large stocks can follow. Without short selling, arbitrage is
slow, so the fast part lasts long enough to trade. The sleeve measures that fast part with a z-score against the last 40
bars, and trades against it when it passes 1.5.

### 10. Intraday momentum, measured several ways · 1:15

The Momentum sleeve. Momentum is one of the best documented effects in finance: past winners keep winning, futures trend against
their own past, and within a day, the first half hour predicts the last half hour. Each way of measuring momentum is a
weak signal. So the sleeve measures intraday momentum five ways, from the session open, over two hours, within one bar,
plus one counter-force, the distance to VWAP, and combines them with a Ridge regression, a regularized linear model. The penalty keeps the
weights small and stable, and because the model is linear, I can read every weight.

Running total: 9:15

## Step 2: Data preparation (about 6 minutes)

### 11. 02 Data Preparation (section) · 0:15

Step two: data.

### 12. Two engines, each reading futures and index · 1:00

I use two engines for two purposes. The lab tests the alpha alone; Plutus tests the alpha plus execution. Each reads
two data streams: VN30F1M, the contract we trade, and the VN30 index, which only the Basis sleeve uses. The lab takes
both from DNSE 30-minute candles and infers the contract code from the exchange calendar. Plutus builds both from ticks
in algotradeDB, trades the real contract and charges the real HNX, VSDC and tax amounts.
### 13. One session of bars, 3 June 2021 · 1:15

This is what the data looks like, one session. On the left, ten futures bars with open, high, low, close, volume and
the contract code. On the right, the index close. Each bar is labelled by its start time: the 10 o'clock bar runs to
10:30, so its close is only known at 10:30. The basis column is not in the data; it is what the Basis sleeve computes,
futures close minus index close. Notice 11:30: the index has no bar there, so the sleeve uses the last index close
already known, never a later one.
### 14. The lab's frame, bar by bar · 1:30

This is the frame the lab builds, on the same session; from 13:00 I changed the positions to show more cases. Pos is
the position decided at each close; HoldPos is what is held during the bar, which is simply the previous Pos. At 09:00
the strategy still holds the overnight long, earns plus 5.6, and pays 0.4 to exit. At 10:30 it buys and pays 0.4, but
earns nothing on that bar. At 13:00 it reverses from long to short: two units of change, so 0.8 in fees, while that
bar still earns the long's plus 10.7. At 13:30 the short gains as the price falls. At 14:00 it closes the short, pays
0.4 and takes the short's loss on that bar. Adding Net gives D, plus 10.5 points. The
metrics come from here. Sharpe takes the D of every session, mean over standard deviation, times root 252. Margin
divides total net by the value traded, here 10.5 over 7,506, about 14 basis points. Max drawdown is the largest fall
of the cumulative net, here from 14.4 to 10.5, so 3.9 points.

### 15. Three periods, same dates in both engines · 0:45

The data are split in three. In-sample runs from June 2021 to December 2022; June 2021 is the first date in the
database, so both engines cover the same 401 sessions. Out-of-sample is 2023 to 2024. 2025 is left out, and 2026 up to
October is the forward period, the last check before paper trading.
### 16. Contract roll: the continuous series jumps · 1:00

VN30F1M is always the nearest contract. After expiry, the DNSE series switches to the next contract with no adjustment
and no code, so the first night after expiry gaps 9.5 points on average, against 4.5 on other nights. That extra jump is
the price difference between two contracts, not a market move. I rebuild the code from the exchange calendar, and it
matches the database on every session. Prices stay raw, because the Basis sleeve needs the contract actually trading.
The Basis sleeve restarts on each new contract, and the whole strategy is flat from 14:00 on expiry day, so no position
crosses a roll.

Running total: 15:00

## Step 3: From hypotheses to rules (about 4 minutes)

### 17. 03 From Hypotheses to Rules (section) · 0:15

Step three: turning each hypothesis into exact rules. I write them with parameters; the values come in step 4.

### 18. One score from five momentum features · 1:00

The Momentum sleeve computes one score: an intercept beta zero plus five features, each centred by mu, scaled by s and
clipped at plus or minus c, then weighted by beta. The hypothesis fixes only the signs: the first four betas positive,
the distance to VWAP negative. The rules: long when the score is above theta M, short below minus theta M. Exit on a
loss of L M points, when the score changes sign after h M bars, or after H M bars.

### 19. Trade against extreme basis z-scores · 1:00

The Basis sleeve computes the basis and its z-score over a window of W bars. Long when Z is below minus z in, short
above plus z in. It reverses at the opposite extreme after h B bars, exits on a loss of L B points, or when Z comes back
inside z out.

### 20. Positions set by the date alone · 0:45

Calendar needs no indicator. Long on the weekdays in the set D long, the first k sessions of the month and the session
before a holiday. Short on a regular Monday whose opening gap is at most g max. Long on expiry Thursday until T end.
Each auxiliary leg can be switched on or off.

### 21. Combining the sleeves · 1:00

Each sleeve gives minus one, zero or plus one, and the ensemble weights them by w M, w B and w C. Majority vote takes
the sign of the weighted sum: it trades a full position as soon as the sleeves lean one way. The sum keeps the weighted
sum itself, so the size grows with agreement. On Plutus the vote trades N contracts per unit of position.

The timing rules from step 2 apply to both: the next bar, the closing auction repeating 14:00, and flat from 14:00 on
expiry day.

Running total: 19:00

## Step 4: In-sample backtesting (about 7 minutes)

### 22. 04 In-Sample Backtesting (section) · 0:15

Step four. First the starting values, then how I measure, then the in-sample results.

### 23. Starting values: the frozen package as is · 1:00

Step four runs the rules with the values already in the frozen package, nothing tuned. For Momentum, the five betas
with their centres and scales; all five signs match the hypothesis. These were fitted on 2020 to 2022 before
packaging, which overlaps the in-sample period, and I come back to that in step 6. The entry threshold is 0.18, holding
2 to 8 bars, a 10-point stop. Basis uses a 40-bar window, enters at a z-score of 1.5 and stops at 14 points. Calendar
buys Tuesday, Wednesday and the first two sessions of the month, and the Monday gap threshold is zero. The three
sleeves have equal weight.

### 24. How the lab scores a strategy · 1:00

In the lab, each bar earns the previous position times the price change, minus 0.4 points per unit of position change.
Sharpe is computed on daily net points, flat days included, annualized with root 252. Margin, here, means profit per
unit of value traded, in basis points, not collateral. Max drawdown is the largest fall of cumulative net points from a
peak.

### 25. How Plutus scores a strategy · 0:45

Plutus measures in money. Sharpe is computed on the daily return of account equity. Net PnL in dong divided by
100,000 gives index points. And margin utilisation is the collateral side: margin required over margin assets, with a
warning at 80 percent and a margin call at 90.

### 26. The same session in both engines · 1:00

Now the two formulas on one session. On the left, the lab, on one session: the vote on 3 June 2021. The line is the price of each
30-minute bar, and the shaded areas are the bars where we hold a long position. At 09:00 the position goes from plus one to zero. That bar still earns the overnight move of the position
we were holding, plus 5.6 points, and pays 0.4 for the exit. At 10:30 we go long again and pay another 0.4. Add up the
bars at the bottom and you get the session's result, D equals plus 10.1 points. The lab Sharpe is the mean of these daily D
values over their standard deviation, times root 252.

On the right, Plutus records the account once per session. Equity starts at 300 million; r is the daily percentage
change of equity after charges, and the Plutus Sharpe is computed on r the same way. That is why the two Sharpe ratios
are not directly comparable: one is on points per contract, the other on returns on capital.

### 27. Both ensembles are profitable in-sample · 1:00

In the lab, per contract, the majority vote earns 1,579 points with a Sharpe of 3.70. The sum earns 800 points with a
Sharpe of 3.60. The vote earns more because it holds a full contract whenever two sleeves agree. But look at the
drawdown: 40 points for the sum against 88 for the vote.

### 28. Profitable after real charges, far from a margin call · 1:00

On Plutus, with 300 million and up to three contracts, the vote returns plus 150 percent over the in-sample period and
the sum plus 104 percent. The sum has the higher Sharpe, 4.37 against 4.12, and a lower drawdown, 3.2 against 5.1
percent. Peak margin use stays around 20 percent, with no warning and no margin call.

### 29. Same direction, different execution · 1:00

How do the two engines compare? Three findings. The data agree: the lab gives the same result on DNSE and on the
database, within one percent. Real costs are lower than the lab assumes, about 0.13 points per contract per side
against 0.4. And fill timing differs: daily PnL in the two engines correlates at 0.89, and orders that cannot fill are
sent again one bar later. So the sizes differ, but the direction of every result is the same.

Running total: 26:00

## Step 5: Optimization (about 7 minutes)

### 30. 05 Optimization (section) · 0:15

Step five. Here the risk is to fool myself, so I start with the rule.

### 31. The selection rule, fixed before the tests · 1:00

Three rules, written before the tests. Sharpe after fee decides. A gap below 0.2 is a tie, and a tie goes to the lower
drawdown, then to fewer rules. Parameter grids only check stability: the neighbours of each frozen value must stay
profitable with at least 70 percent of its Sharpe, and I never replace a frozen value with a neighbour. That gives six
new trials, listed on the right. To be transparent: I had already seen the vote and sum results when I wrote this
rule.

### 32. Each sleeve added lifts the Sharpe · 0:45

Single sleeves reach a Sharpe of 1.8 to 2.3. Any pair reaches 3.1 to 3.3. All three reach 3.6 to 3.7. Each sleeve you
add lifts the result.

### 33. More profit or less drawdown · 0:45

This chart shows the trade-off. The vote has the most profit. The sum has by far the lowest drawdown. Everything else
sits in between.

### 34. The sleeves barely move together · 0:45

This is why combining works. Momentum and Basis correlate at 0.17, Momentum and Calendar at 0.14, and Basis and Calendar at
minus 0.21: one tends to gain when the other loses.

### 35. Sleeves earn in different months · 0:45

You can see it month by month. In September and October 2022, Calendar lost while Momentum gained. In May 2022, Basis
lost while Calendar and Momentum gained. The combined vote lost in only one month out of nineteen.

### 36. Agreement doubles the edge per bar · 1:00

This chart explains vote against sum. Half of the time only one sleeve is on one side. When two sleeves agree, the
next-bar move in their direction is almost twice as large: 0.84 points against 0.45. The vote trades a full contract
from a single sleeve; the sum sizes with agreement. That is why the sum has a much lower drawdown.

### 37. Three checks on the sleeves · 1:00

The three checks. Calendar with all its legs beats the core legs alone by 0.45 Sharpe, so the auxiliary legs stay.
The Momentum threshold is stable: both neighbours keep about 90 percent of the Sharpe. The Basis window is not stable on the
short side: a 30-bar window keeps only 63 percent. Under the rule, I keep the frozen window of 40 and watch that edge
out of sample.

### 38. Carried into step 6 · 0:30

The decision. The official ensemble is the equal-weight sum: its Sharpe ties with the vote and its drawdown is less
than half. The vote runs alongside for reference. All parameters stay as frozen.

Running total: 32:45

## Step 6: Out-of-sample backtesting (about 4.5 minutes)

### 39. 06 Out-of-Sample Backtesting (section) · 0:15

Step six, the out-of-sample test.

### 40. Still profitable out of sample, with less edge · 1:00

In the lab, both ensembles stay profitable in 2023 to 2024 and in 2026. But the edge shrinks: the sum's Sharpe goes
from 3.60 in-sample to 2.36 and then 1.54, and the profit per unit traded halves. The sum keeps a lower drawdown than
the vote in every period.

### 41. Real charges, real contracts, still positive · 1:00

On Plutus, the sum returns plus 46 percent over 2023 to 2024, with a Sharpe of 2.78 and a drawdown of 3.2 percent, and
plus 36 percent over January to October 2026, with a Sharpe of 2.56 and a drawdown of 5.1 percent. No margin call in any
run. The forward runs are flagged FAILED because Plutus could not evaluate two sessions and left them out.

### 42. The decay comes from Momentum · 1:00

Where does the decay come from? Look at the left panel. Basis and Calendar keep a Sharpe above 1.3 in every period.
Momentum falls from 2.23 in-sample to 0.91, and loses money in 2026. The ensembles follow Momentum down, but stay positive.

### 43. What to do with Momentum · 1:15

Two explanations fit. The Momentum weights were fitted on 2020 to 2022, which overlaps the in-sample period, so its
in-sample numbers were inflated. And the momentum edge may be fading, as my protocol predicted. My provisional verdict is
to remove Momentum from the main signal, or to refit it.

But I did not simply drop it. On the right, Basis and Calendar alone do better in 2026, but worse in 2023 to 2024, and
with a higher drawdown in every period. And I chose this combination after seeing these data, so it is a new candidate,
not a result.

Running total: 37:15

## Closing (about 1 minute)

### 44. Summary · 1:00

To summarize. Three independent sleeves, combined by an equal-weight sum, stay profitable out of sample after real
exchange charges. The drawdown stays around 3 to 5 percent on 300 million dong, with no margin call. And Momentum is
decaying, so the next test, on new data from October 2026, will run the full strategy and the version without Momentum
side by side. Thank you. I am happy to take your questions.

Total: about 38:15
