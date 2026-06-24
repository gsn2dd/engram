import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from path_memory.temporal import temporal_status, STATUS_UPCOMING, STATUS_CURRENT, STATUS_PAST


class TestTemporalStatus(unittest.TestCase):
    def test_no_anchor_returns_none(self):
        self.assertIsNone(temporal_status(None))
        self.assertIsNone(temporal_status(None, date(2026, 7, 1)))

    def test_single_day_event_upcoming(self):
        status = temporal_status(date(2026, 12, 25), today=date(2026, 6, 22))
        self.assertEqual(status, STATUS_UPCOMING)

    def test_single_day_event_on_the_day_is_current(self):
        status = temporal_status(date(2026, 6, 22), today=date(2026, 6, 22))
        self.assertEqual(status, STATUS_CURRENT)

    def test_single_day_event_past(self):
        status = temporal_status(date(2026, 1, 1), today=date(2026, 6, 22))
        self.assertEqual(status, STATUS_PAST)

    def test_anchor_end_defaults_to_anchor_start(self):
        # No anchor_end given — a single day, not an open-ended range.
        self.assertEqual(
            temporal_status(date(2026, 6, 22), today=date(2026, 6, 23)),
            STATUS_PAST,
        )

    def test_date_range_current_on_first_day(self):
        status = temporal_status(date(2026, 7, 24), date(2026, 8, 9), today=date(2026, 7, 24))
        self.assertEqual(status, STATUS_CURRENT)

    def test_date_range_current_on_last_day(self):
        status = temporal_status(date(2026, 7, 24), date(2026, 8, 9), today=date(2026, 8, 9))
        self.assertEqual(status, STATUS_CURRENT)

    def test_date_range_current_mid_range(self):
        status = temporal_status(date(2026, 7, 24), date(2026, 8, 9), today=date(2026, 8, 1))
        self.assertEqual(status, STATUS_CURRENT)

    def test_date_range_upcoming_before_start(self):
        status = temporal_status(date(2026, 7, 24), date(2026, 8, 9), today=date(2026, 6, 22))
        self.assertEqual(status, STATUS_UPCOMING)

    def test_date_range_past_after_end(self):
        status = temporal_status(date(2026, 7, 24), date(2026, 8, 9), today=date(2026, 9, 1))
        self.assertEqual(status, STATUS_PAST)

    def test_olympics_example_next_year_then_now_then_past(self):
        # "Next year's Olympics" written while it's still in the future...
        olympics_start, olympics_end = date(2028, 7, 14), date(2028, 7, 30)
        self.assertEqual(
            temporal_status(olympics_start, olympics_end, today=date(2027, 1, 1)),
            STATUS_UPCOMING,
        )
        # ...becomes "the current Olympics" while it's happening...
        self.assertEqual(
            temporal_status(olympics_start, olympics_end, today=date(2028, 7, 20)),
            STATUS_CURRENT,
        )
        # ...and "when the Olympics were" once it's over — all from the same
        # frozen anchor dates, with no rewrite of the stored row required.
        self.assertEqual(
            temporal_status(olympics_start, olympics_end, today=date(2029, 1, 1)),
            STATUS_PAST,
        )


if __name__ == "__main__":
    unittest.main()
