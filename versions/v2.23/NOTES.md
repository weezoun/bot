# v2.23 — 2026-10-07

Previous version: [v2.22](../v2.22/NOTES.md)

## What changed since v2.22

This checkpoint reverts all strategy changes made in v2.22 and the subsequent commit (`e585281`) **exclusively for XAUUSD (Gold)**, keeping the other five symbols (Indices and Currencies) completely intact, and documents the dashboard guest credential update.

### 1. Reversal of v2.22 & commit e585281 for XAUUSD (Gold) only

User's verbatim instruction: *"current version aur commit may ki gaye tamam changes reverse kerni hein lekin sirf XAUUSD (gold) k liye baqi sub ko intact rehne do un ko baad may dekh lein ge."*

In v2.22, XAUUSD was included in the global ATR check removal and the new `condition == 'RANGING'` trade block, followed by commit `e585281` removing the DI-regime-flip shortcut for Gold and currency pairs. All three of these changes are now reversed for Gold:

- **ATR check restored (`config.XAUUSD.atr_check_enabled = True`)**:
  Re-enforces the `snap.atr_strong` requirement for Gold's Rule 5 (scalp entry), Rule 6 gate (`_check_rule6_gate`), and Rule 3 gate (`_check_rule3_gate`). Gold now filters out choppy low-ATR scalps and re-arm attempts, exactly as it did in v2.21 and earlier.
- **Condition check removed (`config.XAUUSD.condition_check_enabled = False`)**:
  Removes the `condition != 'RANGING'` block from Gold across all rules (Rule 2 entry, Rule 5 scalp entry, Rule 3 gate, Rule 4 gate, Rule 6 gate, and Rule 7 reversal gate). Gold no longer evaluates or blocks on market condition (NORMAL/RANGING/VOLATILE), restoring its pre-v2.22 behavior.
- **DI regime flip shortcut restored (`config.XAUUSD.regime_flip_force_rearm = True`)**:
  Reverts commit `e585281` for Gold. When the DI regime flips, `scalp_armed` is re-armed to `True` and `scalp_continuation_gate` / `rule7_reversal_gate` are cleared, restoring the original design behavior on Gold.

### 1b. Gold's Rule 7 — two remaining unflagged v2.22 changes also reverted (follow-up audit, same day)

A full v2.21→current code audit found two v2.22 changes inside `bot_runner._gate_scalp_reversal` (Gold's Rule 7) that sat behind NO flag, so they were still live on Gold after section 1. The same function is also used by GBPUSD/USDJPY (`SCALP_SL_REVERSAL_COOLDOWN=True`), so each got its own per-symbol flag (default `True` = unchanged behavior; `False` on XAUUSD only):

- **`RULE7_PROFIT_SKIPS_COOLDOWN`** (wraps the 2026-09-03 correction): `False` on Gold → the `RULE4_MIN_COOLDOWN_SECONDS` floor applies on EVERY scalp SL, profit or loss, exactly as v2.21.
- **`RULE7_SCALP_SIDE_REARM`** (wraps the 2026-09-04 fix): `False` on Gold → a scalp SL no longer sets Rule 6's `scalp_continuation_gate`; v2.21's own log line restored verbatim.

REASON (user's own words): *"sirf gold k rules ko reverse kia hai bus us ko confirm kerlo kuch hi reversal se reh na jaye."*

IMPACT on Gold: after a profit-closed scalp SL the reversal side waits the full cooldown again. The 2026-09-04 bug comes back on purpose: Gold's scalp side re-arms only on a DI-regime flip again (`REGIME_FLIP_FORCE_REARM=True`), so "already scalped this DI regime" can stay stuck until the next flip. To undo just that part, set `rule7_scalp_side_rearm=True` on XAUUSD.

Audit result: every other v2.21→current difference that touches Gold is now either behind one of these 5 flags (all set to v2.21 values on XAUUSD) or is comment/log text only. Non-rule items left as they are: the dashboard Summary toggle (`/api/trades/summary`, `trade_store.get_daily_summary`), the MT5 login and the guest password.

Dashboard (`app.py._build_rules()`): Rules 2-7 cards each get an "XAUUSD REVERTED, 2026-10-07" line (wording later changed to "v2.20", see 1c), and the stale "ALL 6 symbols" / "XAUUSD/GBPUSD/USDJPY only" headers are corrected.

### 1c. v2.21 reverted for Gold too — Gold is back to its frozen v2.18/v2.20 state

Checked the version history to find the last known-good point for Gold. Gold was separated/frozen on **2026-08-29 (v2.18)** because it was clearly profitable: week of 23-29 Aug, 607 trades, 49.3% win, net **+11,084.00**. Changes that touched Gold after that freeze:

- v2.19 (29 Aug) and v2.20 (1-2 Sep): **none**. Indices only. Gold's config block is byte-identical v2.18 → v2.20 (non-comment lines). `SCALP_SL_PROFIT_SKIP_REVERSAL` was added in v2.20 but defaults False, so Gold never used it.
- **v2.21** (2 Sep): Gold's Rule 7 redesign (`SCALP_SL_REVERSAL_COOLDOWN=True`).
- **v2.22** (3-4 Sep) + commit e585281: ATR removal, condition check, the two Rule 7 corrections, and the regime-flip removal. All of these were already reverted above.

REASON (user's own words): *"gold ko jis din alag kia tha woh bhi actually us k profit may hone ka saboot tha... us k baad dekhte hein gold may kia kia changes ki hein ager us k baad v 2.21 aur 2.22 they to un dono ko hi reverse kerna hoga."*

Change: `config.XAUUSD.scalp_sl_reversal_cooldown = False`. All of v2.21 sat behind this single flag (verified with a non-comment code diff v2.20 → current), so a scalp SL on Gold goes back to the classic immediate `_reverse_scalp()`, capped once per DI regime, and `rule7_reversal_gate` is never set on Gold. The two `RULE7_*` flags from section 1b are now moot on Gold. They stay `False`, so flipping the cooldown flag back to True would restore v2.21's exact Rule 7.

IMPACT / trade-off, accepted: in the v2.20 data the immediate reversal was net-negative for Gold. Loss-triggered: 12x, 8% win, −1,689 on the reversal leg (−3,988 combined with the scalp's own loss). Profit-triggered: −234. The user chose the whole frozen state, which was profitable overall, over that per-rule fix.

Verified with a standalone dispatch test (no MT5 connection): a scalp SL on XAUUSD, profit or loss, now calls the immediate reversal. GBPUSD/USDJPY still use the Rule 7 cooldown gate. USA500 is unchanged (profit → re-arm via Rule 6, loss → immediate reversal). Every non-comment code difference v2.20 → current is behind a per-symbol flag, and all five flags are at their v2.20-equivalent values on XAUUSD: `SCALP_SL_REVERSAL_COOLDOWN=False`, `ATR_CHECK_ENABLED=True`, `CONDITION_CHECK_ENABLED=False`, `REGIME_FLIP_FORCE_REARM=True`, `SCALP_SL_PROFIT_SKIP_REVERSAL=False`.

Dashboard: the Rule 2-7 cards now say "XAUUSD REVERTED TO v2.20 (its frozen v2.18 state)". The Rule 7 card and the summary row now show Gold on the classic immediate reversal.

### 2. Five non-Gold symbols remain completely intact

The symbol isolation boundary was strictly maintained with zero cross-contamination:

- **Indices (USA500, USA100, USA30)**:
  - `ATR_CHECK_ENABLED = False` (unchanged)
  - `CONDITION_CHECK_ENABLED = True` (unchanged)
  - `REGIME_FLIP_FORCE_REARM = True` (unchanged)
  - `SCALP_SL_PROFIT_SKIP_REVERSAL = True` (unchanged)
- **Currencies (GBPUSD, USDJPY)**:
  - `SCALPING_ENABLED = True`, `FLIP_ENABLED = True` (unchanged)
  - `ATR_CHECK_ENABLED = False` (unchanged)
  - `CONDITION_CHECK_ENABLED = True` (unchanged)
  - `REGIME_FLIP_FORCE_REARM = False` (unchanged)
  - `SCALP_SL_REVERSAL_COOLDOWN = True` (unchanged, Gold's Rule 7 mechanism)

### 3. Dashboard guest credential update

- In `config.py`: `DASHBOARD_GUEST_PASSWORD` updated from `"14august"` to `"effortless"`.

### 4. MT5 demo account changed

- In `config.py`: `MT5_LOGIN` updated from `49825877` to `49867955` (same `MT5_SERVER = "HFMarketsGlobal-Demo"`).
- REASON (user's own words): *"mt5 ka account meine change kia hai purana wala demo account expire ho gaya tha"* — the old demo account expired, so a new demo account was opened.
- IMPACT: no strategy/rule change. `trade_store.py` keys the history table per login (`trade_history_<MT5_LOGIN>`), so the bot now writes to a fresh `trade_history_49867955` table; the old account's trades stay in `trade_history_49825877` and won't show in the dashboard's history/stats for the new account.

### 5. Infrastructure & environment

- Python 3.14 dependencies installed and verified on the Windows host (`MetaTrader5==5.0.6231`, `Flask==3.1.3`, `pandas==3.0.6`, `numpy==2.5.3`).
- Verified that all imports (`MetaTrader5`, `flask`, `pandas`, `numpy`, `msvcrt`) succeed on the Windows runtime.
- Bot remains stopped per explicit user instruction (*"stop rehne do abhi is ko run nahi karo"*).

## Verification

- **Standalone tests verified**:
  - In `condition == 'RANGING'`: XAUUSD successfully fires WITH_TREND signals (`CONDITION_CHECK_ENABLED = False`), whereas USA500 is blocked (`CONDITION_CHECK_ENABLED = True`).
  - With `atr_strong = False`: XAUUSD scalp is blocked (`ATR_CHECK_ENABLED = True`), whereas USA500 scalp fires (`ATR_CHECK_ENABLED = False`).
  - On DI regime flip: XAUUSD re-arms scalp (`REGIME_FLIP_FORCE_REARM = True`), whereas GBPUSD remains gated (`REGIME_FLIP_FORCE_REARM = False`).
- `python -m py_compile` clean on `config.py`, `strategy.py`, `bot_runner.py`, and `app.py`.
- Documentation in `docs/current_strategy.md` updated to record the XAUUSD reversion.

## Baseline at save time

- `stats/trade_history_at_v2.23_save.db` — snapshot of SQLite trade history.

## Next version

(none yet)
