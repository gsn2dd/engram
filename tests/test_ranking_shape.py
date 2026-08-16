"""
The use-history term must not be able to answer a question it is not about.

These tests exist because that failure has now happened TWICE in the same
codebase, in two different disguises:

  1. Additive ranking made weight (0.7) a peer of cosine (0.1), so a warmed
     cluster outranked exact matches outright. Fixed by making use-history a
     bounded multiplier.
  2. The multiplier normalised weight against the pool MAXIMUM. On a heavy-
     tailed corpus (measured: mean 0.19, max 5.83, only 15% of memories carrying
     any weight at all) that handed nearly the whole bonus to a handful of
     memories and promoted them into every result set — the same defect, at a
     smaller amplitude, invisible to a test that only checked the coefficient.

Both slipped through because nothing tested the SHAPE of the transform. A test
asserting `USE_BONUS == 0.5` would have passed happily through defect 2. So
these tests assert behaviour on a distribution, which is the thing that actually
has to hold.

Written with unittest, not pytest: CI installs requirements.txt and runs
`unittest discover`, so a bare `import pytest` here is an import error that
fails the whole module rather than a missing dependency anyone would notice.
"""
import unittest

from path_memory.recall import _normalise_weights, _policy, DEFAULT_POLICY

# A realistic heavy tail: most memories cold, a few very hot. Shaped like the
# measured mindspace distribution rather than invented.
HEAVY_TAIL = [0.0] * 12 + [0.05, 0.1, 0.2, 0.4] + [4.8, 5.8]


class TestWeightNormalisation(unittest.TestCase):

    def test_max_normalisation_starves_the_middle(self):
        """Documents the defect, so the reason for the default is not lost.

        Under max-normalisation a mid-weight memory — one that has genuinely
        proven useful several times — receives almost none of the available
        bonus, because the scale is set by an outlier it will never approach.
        """
        norm = _normalise_weights(HEAVY_TAIL, "max")
        mid = norm[HEAVY_TAIL.index(0.4)]
        self.assertAlmostEqual(max(norm), 1.0)
        self.assertLess(mid, 0.10,
                        "max-norm should be shown starving the middle of the distribution")

    def test_rank_normalisation_gives_the_middle_a_real_share(self):
        """The default must let a proven-useful memory actually feel the bonus."""
        norm = _normalise_weights(HEAVY_TAIL, "rank")
        mid = norm[HEAVY_TAIL.index(0.4)]
        self.assertTrue(0.5 < mid < 1.0,
                        f"a memory used more than most should sit high on rank, got {mid}")

    def test_rank_normalisation_does_not_invent_an_order_among_ties(self):
        """85% of a real corpus has weight exactly 0.

        If ties were broken by sort order, that silent majority would be handed
        a spread of use-scores derived from nothing at all — a fabricated
        ranking that would look exactly like evidence.
        """
        norm = _normalise_weights([0.0, 0.0, 0.0, 0.0, 1.0], "rank")
        self.assertEqual(len(set(norm[:4])), 1, "tied weights must receive identical scores")
        self.assertGreater(norm[4], norm[0])

    def test_empty_pool_is_not_an_error(self):
        """recall() calls this before it knows whether anything matched."""
        self.assertEqual(_normalise_weights([], "rank"), [])


class TestBonusCannotOverturnRelevance(unittest.TestCase):

    def test_bonus_cannot_overturn_a_clear_relevance_gap(self):
        """The property that matters, expressed as the arithmetic recall performs.

        A cold but clearly-relevant memory must beat a maximally-warm but less
        relevant one. This is the invariant both historical defects violated.
        """
        pol = _policy(None)
        hot = 1.0 + pol["use_bonus"] * (pol["w_weight"] * 1.0 + pol["w_recency"] * 1.0)
        relevant_cold = 0.75 * 1.0
        less_relevant_hot = 0.60 * hot
        self.assertGreater(
            relevant_cold, less_relevant_hot,
            f"use-history bonus {hot:.3f}x is large enough to overturn a "
            f"0.75-vs-0.60 cosine gap; it must not be")


class TestPolicyPlumbing(unittest.TestCase):

    def test_defaults_are_the_measured_ones(self):
        """A guard on the pair, not on either number alone.

        use_bonus and weight_norm were tuned together against the bench;
        changing one without re-running it silently discards the other's
        justification.
        """
        self.assertEqual(DEFAULT_POLICY["weight_norm"], "rank")
        self.assertEqual(DEFAULT_POLICY["use_bonus"], 0.1)

    def test_unknown_policy_key_is_rejected(self):
        """A typo'd key would make a bench rung report a policy it never ran."""
        with self.assertRaises(ValueError):
            _policy({"use_bonuss": 0.3})

    def test_none_policy_is_exactly_the_defaults(self):
        self.assertEqual(_policy(None), dict(DEFAULT_POLICY))


if __name__ == "__main__":
    unittest.main()
