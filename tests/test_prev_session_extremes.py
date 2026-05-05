"""Regression tests for indicators/structure/prev_session_extremes.py.

Covers the two correctness-critical behaviors of the indicator:

  T1 — No dead-zone leak across NY -> dead zone -> Asia transition.
       Asia at 00:00 UTC must reference the prior-day NY's high/low, not
       anything that happened during the 21:00-00:00 UTC dead zone.

  T2 — Inside-open arms immediately (Rule 1).
       If the first bar of a real session opens at-or-inside the prev-extreme
       reference, armed_long/armed_short is True from bar 1 — the first
       close-break in that session is eligible without any prior in-session
       "inside" bar.

  T3 — Gap-open requires re-arm (Rule 2).
       If the first bar opens past the prev-extreme reference, armed stays
       False until a subsequent bar in the same session closes back inside,
       at which point armed flips True for following bars.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from indicators.structure.prev_session_extremes import prev_session_extremes  # noqa: E402


def _make_sc(session_ids, session_seqs, highs_running, lows_running, start="2024-01-02 18:00:00"):
    """Build a synthetic session_clock-shaped DataFrame."""
    idx = pd.date_range(start, periods=len(session_ids), freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "session_id": session_ids,
            "session_seq": session_seqs,
            "session_high_running": highs_running,
            "session_low_running": lows_running,
        },
        index=idx,
    )


def _make_df(opens, closes, idx):
    """Build a minimal OHLC frame matching the supplied index."""
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 1 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 1 for o, c in zip(opens, closes)],
            "close": closes,
        },
        index=idx,
    )


class T1_NoDeadZoneLeak(unittest.TestCase):
    """NY (200/150) -> dead zone (310/90 — extreme) -> next-day Asia.
    Asia must see prev_session marks of 200/150 (NY's), not 310/90 (dead zone)."""

    def test_asia_does_not_leak_dead_zone_extremes(self):
        # 4 NY bars (seq=10), 4 dead-zone bars (seq=11), 5 Asia bars (seq=12)
        session_ids = ["ny"] * 4 + ["none"] * 4 + ["asia"] * 5
        session_seqs = [10] * 4 + [11] * 4 + [12] * 5
        # NY running extremes finalize at 200 / 150 on bar 3.
        highs = [195, 198, 200, 200,
                 300, 305, 310, 310,
                 220, 225, 225, 225, 225]
        lows = [160, 155, 150, 150,
                100, 95, 90, 90,
                210, 210, 210, 210, 210]

        sc = _make_sc(session_ids, session_seqs, highs, lows)
        df = _make_df([180.0] * 13, [180.0] * 13, sc.index)

        result = prev_session_extremes(sc, df)

        # During NY there is no prior real session in the fixture -> NaN.
        for i in range(0, 4):
            self.assertTrue(
                pd.isna(result.iloc[i]["prev_session_high"]),
                f"NY bar {i} should have NaN prev_session_high (no prior session in fixture)",
            )

        # First dead-zone bar (idx=4): prev marks become NY's final extremes.
        self.assertEqual(result.iloc[4]["prev_session_high"], 200)
        self.assertEqual(result.iloc[4]["prev_session_low"], 150)
        self.assertEqual(result.iloc[4]["prev_session_id"], "ny")

        # Through the dead zone: marks must remain NY's 200/150 — the
        # dead zone must NOT publish its own 310/90.
        for i in range(4, 8):
            self.assertEqual(
                result.iloc[i]["prev_session_high"], 200,
                f"Dead zone bar {i} leaked: prev_session_high={result.iloc[i]['prev_session_high']}",
            )
            self.assertEqual(
                result.iloc[i]["prev_session_low"], 150,
                f"Dead zone bar {i} leaked: prev_session_low={result.iloc[i]['prev_session_low']}",
            )
            self.assertEqual(result.iloc[i]["prev_session_id"], "ny")

        # First Asia bar (idx=8, 00:00 UTC the next day) — the regression target.
        # Marks must STILL be NY's 200/150, NOT dead zone's 310/90.
        self.assertEqual(
            result.iloc[8]["prev_session_high"], 200,
            f"DEAD-ZONE LEAK: Asia first bar prev_session_high={result.iloc[8]['prev_session_high']}, expected 200",
        )
        self.assertEqual(
            result.iloc[8]["prev_session_low"], 150,
            f"DEAD-ZONE LEAK: Asia first bar prev_session_low={result.iloc[8]['prev_session_low']}, expected 150",
        )
        self.assertEqual(result.iloc[8]["prev_session_id"], "ny")

        # All Asia bars: same — no late leak.
        for i in range(8, 13):
            self.assertEqual(result.iloc[i]["prev_session_high"], 200)
            self.assertEqual(result.iloc[i]["prev_session_low"], 150)
            self.assertEqual(result.iloc[i]["prev_session_id"], "ny")


class T2_InsideOpenArmedImmediately(unittest.TestCase):
    """If session opens INSIDE prev-extreme reference, armed_* is True
    from bar 1 — no prior 'inside' bar required for re-arm."""

    def test_long_armed_from_bar_one_when_open_inside(self):
        # Prior NY ends with high=200, low=150.
        # Asia bar 0 opens at 180 (inside long-side ref 200) and closes at 210
        # (above ref). With Rule 1 active, armed_long must be True from bar 0.
        session_ids = ["ny"] * 4 + ["asia"] * 4
        session_seqs = [1] * 4 + [2] * 4
        highs = [195, 198, 200, 200, 185, 210, 215, 215]
        lows = [160, 155, 150, 150, 178, 178, 178, 178]

        sc = _make_sc(session_ids, session_seqs, highs, lows)
        df = _make_df(
            opens=[180] * 4 + [180, 180, 180, 180],
            closes=[180] * 4 + [210, 200, 200, 200],
            idx=sc.index,
        )

        result = prev_session_extremes(sc, df)

        # First Asia bar (idx=4) has prev_session_high=200, open=180 (inside).
        self.assertEqual(result.iloc[4]["prev_session_high"], 200)
        self.assertTrue(
            result.iloc[4]["armed_long"],
            "First-bar long armed_long must be True when session opens inside ref "
            f"(open=180, prev_high=200); got armed_long={result.iloc[4]['armed_long']}",
        )

    def test_short_armed_from_bar_one_when_open_inside(self):
        # Mirror of long case. NY ends with low=150. Asia bar 0 opens at 180
        # (inside short-side ref 150 from above: open >= prev_low). Symmetric.
        session_ids = ["ny"] * 4 + ["asia"] * 4
        session_seqs = [1] * 4 + [2] * 4
        highs = [195, 198, 200, 200, 185, 185, 185, 185]
        lows = [160, 155, 150, 150, 175, 140, 140, 140]

        sc = _make_sc(session_ids, session_seqs, highs, lows)
        df = _make_df(
            opens=[180] * 4 + [180, 180, 180, 180],
            closes=[180] * 4 + [140, 150, 150, 150],
            idx=sc.index,
        )

        result = prev_session_extremes(sc, df)

        self.assertEqual(result.iloc[4]["prev_session_low"], 150)
        self.assertTrue(
            result.iloc[4]["armed_short"],
            "First-bar short armed_short must be True when session opens inside ref "
            f"(open=180, prev_low=150); got armed_short={result.iloc[4]['armed_short']}",
        )


class T3_GapOpenRequiresRearm(unittest.TestCase):
    """If session opens BEYOND prev-extreme reference, armed_* stays False
    until a subsequent bar closes back inside (re-arm)."""

    def test_long_gap_open_blocked_until_rearm(self):
        # Prior NY high=200. Asia gap-opens at 220 (above 200).
        # Bar 0: open=220, close=225  -> still above, no re-arm
        # Bar 1: open=225, close=210  -> still above
        # Bar 2: open=210, close=195  -> closes INSIDE ref (re-arm registers)
        # Bar 3: open=195, close=210  -> close-break, but with armed_long now True
        session_ids = ["ny"] * 4 + ["asia"] * 4
        session_seqs = [1] * 4 + [2] * 4
        highs = [195, 198, 200, 200, 225, 225, 225, 225]
        lows = [160, 155, 150, 150, 220, 210, 195, 195]

        sc = _make_sc(session_ids, session_seqs, highs, lows)
        df = _make_df(
            opens=[180] * 4 + [220, 225, 210, 195],
            closes=[180] * 4 + [225, 210, 195, 210],
            idx=sc.index,
        )

        result = prev_session_extremes(sc, df)

        # Bar 0 of Asia (idx=4): gap-open above ref. armed_long must be False.
        self.assertFalse(
            result.iloc[4]["armed_long"],
            f"Gap-open first bar must NOT be armed_long; got {result.iloc[4]['armed_long']}",
        )
        # Bar 1 (idx=5): still no in-session "inside" close. False.
        self.assertFalse(result.iloc[5]["armed_long"])
        # Bar 2 (idx=6): closes inside, but prior_below excludes self -> still False
        # at this bar. (Re-arm becomes visible from the NEXT bar onward.)
        self.assertFalse(
            result.iloc[6]["armed_long"],
            "armed_long must remain False at the bar that itself closes inside "
            "(prior count excludes the current bar).",
        )
        # Bar 3 (idx=7): bar 2 closed inside -> prior_below=1 -> armed_long=True.
        self.assertTrue(
            result.iloc[7]["armed_long"],
            f"After re-arm bar, armed_long must be True; got {result.iloc[7]['armed_long']}",
        )

    def test_short_gap_open_blocked_until_rearm(self):
        # Symmetric short case: prev_low=150, Asia gap-opens at 130 (below 150).
        session_ids = ["ny"] * 4 + ["asia"] * 4
        session_seqs = [1] * 4 + [2] * 4
        highs = [195, 198, 200, 200, 135, 135, 155, 155]
        lows = [160, 155, 150, 150, 125, 125, 125, 125]

        sc = _make_sc(session_ids, session_seqs, highs, lows)
        df = _make_df(
            opens=[180] * 4 + [130, 125, 140, 155],
            closes=[180] * 4 + [125, 140, 155, 140],
            idx=sc.index,
        )

        result = prev_session_extremes(sc, df)

        self.assertFalse(
            result.iloc[4]["armed_short"],
            f"Gap-open first bar must NOT be armed_short; got {result.iloc[4]['armed_short']}",
        )
        self.assertFalse(result.iloc[5]["armed_short"])
        self.assertFalse(
            result.iloc[6]["armed_short"],
            "armed_short must remain False at the bar that itself closes inside.",
        )
        self.assertTrue(
            result.iloc[7]["armed_short"],
            f"After re-arm bar, armed_short must be True; got {result.iloc[7]['armed_short']}",
        )


if __name__ == "__main__":
    unittest.main()
