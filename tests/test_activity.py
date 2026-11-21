import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from subprocess import run
from tempfile import TemporaryDirectory
import sys

from scripts.activity import collect_history, parse_calendar, render, summarize, window_start


class ActivityTests(unittest.TestCase):
    def test_matches_tooltips_by_id_and_handles_english_counts(self):
        fixture = '''<table>
          <td class="ContributionCalendar-day" data-date="2025-12-01" id="a" data-level="4"></td>
          <td class="ContributionCalendar-day" data-date="2025-12-02" id="b" data-level="0"></td>
          <td class="ContributionCalendar-day" data-date="2025-12-03" id="c" data-level="1"></td>
          <tool-tip for="c">1 contribution on December 3rd.</tool-tip>
          <tool-tip for="a">1,234 contributions on December 1st.</tool-tip>
          <tool-tip for="b">No contributions on December 2nd.</tool-tip>
        </table>'''
        self.assertEqual(parse_calendar(fixture, date(2025, 12, 1), date(2025, 12, 3)), {
            date(2025, 12, 1): 1234, date(2025, 12, 2): 0, date(2025, 12, 3): 1,
        })

    def test_missing_unrecognized_or_duplicate_days_fail_closed(self):
        cell = '<td class="ContributionCalendar-day" data-date="2025-12-01" id="a"></td>'
        tooltip = '<tool-tip for="a">No contributions on December 1st.</tool-tip>'
        day = date(2025, 12, 1)
        for fixture in ('', cell, cell + '<tool-tip for="a">Unknown</tool-tip>', cell * 2 + tooltip):
            with self.subTest(fixture=fixture), self.assertRaises(ValueError):
                parse_calendar(fixture, day, day)

    def test_ignores_calendar_padding_outside_requested_range(self):
        cell = '<td class="ContributionCalendar-day" data-date="2025-12-01" id="a"></td>'
        valid = '<tool-tip for="a">2 contributions on December 1st.</tool-tip>'
        padding = '<td class="ContributionCalendar-day" data-date="2025-12-02" id="b"></td>'
        day = date(2025, 12, 1)
        self.assertEqual(parse_calendar(cell + valid + padding, day, day), {day: 2})

    def test_month_boundaries_active_days_and_peak_ties(self):
        today = date(2026, 2, 1)
        self.assertEqual(window_start(today), date(2025, 3, 1))
        summary = summarize({date(2025, 3, 2): 2, date(2025, 3, 3): 0,
                             date(2026, 1, 31): 2, today: 1}, today)
        self.assertEqual(len(summary.months), 12)
        self.assertEqual(summary.months[0], (date(2025, 3, 1), 2))
        self.assertEqual(summary.months[-1], (today, 1))
        self.assertEqual((summary.total, summary.active_days, summary.peak), (5, 3, (date(2026, 1, 1), 2)))

    def test_svg_is_deterministic_accessible_and_marks_partial_month(self):
        today = date(2026, 2, 1)
        card = render(summarize({today: 4}, today))
        root = ET.fromstring(card)
        self.assertEqual(root.attrib['role'], 'img')
        self.assertIn('4 contributions', root.findtext('{http://www.w3.org/2000/svg}desc', default=''))
        self.assertIn('Feb*', card)
        self.assertIn('month in progress', card)
        self.assertEqual(card, render(summarize({today: 4}, today)))

    def test_all_zero_window_does_not_claim_a_peak(self):
        summary = summarize({}, date(2026, 2, 1))
        self.assertEqual(summary.total, 0)
        self.assertIsNone(summary.peak)
        ET.fromstring(render(summary))

    def test_current_streak_can_end_today_or_yesterday_but_not_earlier(self):
        today = date(2026, 2, 3)
        for counts, expected in (
            ({date(2026, 2, 2): 4, today: 9}, 2),
            ({date(2026, 2, 1): 3, date(2026, 2, 2): 4, today: 0}, 2),
            ({date(2026, 2, 1): 3, date(2026, 2, 2): 0}, 0),
            ({}, 0),
        ):
            with self.subTest(counts=counts):
                self.assertEqual(summarize(counts, today).current_streak, expected)

    def test_longest_streak_includes_older_years_and_preserves_chart_window(self):
        today = date(2026, 2, 3)
        counts = {date(2023, 12, 30): 3, date(2023, 12, 31): 1,
                  date(2024, 1, 1): 1, date(2024, 1, 2): 1, date(2024, 1, 3): 2,
                  date(2025, 2, 27): 6, date(2025, 2, 28): 1,
                  date(2025, 3, 1): 1, date(2025, 3, 2): 5,
                  date(2026, 1, 31): 2, date(2026, 2, 1): 2, date(2026, 2, 2): 1,
                  date(2026, 2, 4): 9}
        summary = summarize(counts, today)
        self.assertEqual(summary.longest_streak, 5)
        self.assertEqual((summary.total, summary.active_days), (11, 5))
        self.assertEqual(summarize({d: n for d, n in counts.items() if d.year == 2025}, today).longest_streak, 4)
        self.assertEqual(summarize({}, today).longest_streak, 0)

    def test_svg_exposes_distinct_streak_cards_and_counts_in_description(self):
        today = date(2026, 2, 3)
        root = ET.fromstring(render(summarize({today: 4, date(2026, 2, 2): 1}, today)))
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        texts = {element.text for element in root.findall('.//svg:text', ns)}
        self.assertTrue({'Current streak', 'Longest streak', '2 days'} <= texts)
        self.assertFalse({'Consecutive UTC days', '12-month window', 'All-time'} & texts)
        desc = root.findtext('svg:desc', default='', namespaces=ns)
        self.assertIn('Current streak: 2 days', desc)
        self.assertIn('Longest streak: 2 days', desc)

    def test_history_validates_each_year_and_merges_across_new_year(self):
        def year_page(year):
            first = date(year, 1, 1)
            end = date(year, 12, 31) if year == 2024 else date(2025, 1, 1)
            return ''.join(
                f'<td class="ContributionCalendar-day" data-date="{day}" id="d{i}"></td>'
                f'<tool-tip for="d{i}">{"1 contribution" if day.day in (30, 31) and day.month == 12 or year == 2025 else "No contributions"} on {day}.</tool-tip>'
                for i in range((end - first).days + 1) if (day := first + timedelta(days=i)))

        end = date(2025, 1, 1)
        history = collect_history(2024, end, year_page)
        self.assertEqual((len(history), summarize(history, end).longest_streak), (367, 3))
        with self.assertRaisesRegex(ValueError, 'missing calendar day 2024-01-01'):
            collect_history(2024, end, lambda year: '' if year == 2024 else year_page(year))

    def test_invalid_source_leaves_last_good_svg_untouched(self):
        with TemporaryDirectory() as directory:
            year = datetime.now(timezone.utc).year
            source = Path(directory) / f'{year}.html'
            target = Path(directory) / 'activity.svg'
            source.write_text('<html>rate limited</html>')
            target.write_text('last good chart')
            result = run([sys.executable, '-B', 'scripts/activity.py', 'suxeno', '--source-dir', directory,
                          '--first-year', str(year),
                          '--output', str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing calendar', result.stderr)
            self.assertEqual(target.read_text(), 'last good chart')


if __name__ == '__main__':
    unittest.main()
