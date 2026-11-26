"""Render profile-visible GitHub contribution counts to a repository-local SVG."""
import argparse
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells: list[tuple[date, str]] = []
        self.tooltips: dict[str, list[str]] = {}
        self.tip: str | None = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == 'td' and 'ContributionCalendar-day' in (fields.get('class') or '').split():
            raw_date, cell_id = fields.get('data-date'), fields.get('id')
            if raw_date and cell_id:
                self.cells.append((date.fromisoformat(raw_date), cell_id))
        if tag == 'tool-tip':
            self.tip = fields.get('for')
            if self.tip:
                if self.tip in self.tooltips:
                    raise ValueError('duplicate calendar tooltip')
                self.tooltips[self.tip] = []

    def handle_endtag(self, tag):
        if tag == 'tool-tip':
            self.tip = None

    def handle_data(self, data):
        if self.tip:
            self.tooltips[self.tip].append(data)


def parse_calendar(html: str, start: date, end: date) -> dict[date, int]:
    parser = CalendarParser()
    parser.feed(html)
    parser.close()
    counts: dict[date, int] = {}
    ids: set[str] = set()
    for day, cell_id in parser.cells:
        if not start <= day <= end:
            continue
        if day in counts or cell_id in ids:
            raise ValueError(f'duplicate calendar cell for {day}')
        ids.add(cell_id)
        label = ' '.join(''.join(parser.tooltips.get(cell_id, [])).split())
        match = re.fullmatch(r'(No|\d+|\d{1,3}(?:,\d{3})+) contributions? on .+\.', label)
        if not match:
            raise ValueError(f'missing or unknown calendar count for {day}')
        count = match[1]
        counts[day] = 0 if count == 'No' else int(count.replace(',', ''))
    missing = next((day for i in range((end - start).days + 1)
                    if (day := start + timedelta(days=i)) not in counts), None)
    if missing is not None:
        raise ValueError(f'missing calendar day {missing}; no SVG was written')
    return counts


def collect_history(first_year: int, today: date, load_year: Callable[[int], str]) -> dict[date, int]:
    if not 2005 <= first_year <= today.year:
        raise ValueError('invalid first contribution year')

    def read_year(year: int) -> dict[date, int]:
        return parse_calendar(load_year(year), date(year, 1, 1), min(date(year, 12, 31), today))

    history: dict[date, int] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for days in pool.map(read_year, range(first_year, today.year + 1)):
            history.update(days)
    return history


def shift_month(day: date, offset: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + offset, 12)
    return date(year, month + 1, 1)


def window_start(today: date) -> date:
    return shift_month(today, -11)


@dataclass(frozen=True)
class Summary:
    months: tuple[tuple[date, int], ...]
    total: int
    active_days: int
    peak: tuple[date, int] | None
    current_streak: int
    longest_streak: int


def summarize(counts: dict[date, int], today: date) -> Summary:
    monthly: Counter[date] = Counter()
    active = 0
    streak = longest = 0
    start = window_start(today)
    first = min(min(counts, default=today), today)
    for offset in range((today - first).days + 1):
        day = first + timedelta(days=offset)
        count = counts.get(day, 0)
        if count:
            if day >= start:
                monthly[day.replace(day=1)] += count
                active += 1
            streak += 1
            longest = max(longest, streak)
        elif day != today:
            streak = 0
    window = (shift_month(start, offset) for offset in range(12))
    months = tuple((month, monthly[month]) for month in window)
    peak = max(months, key=lambda item: (item[1], item[0]))
    return Summary(months, sum(n for _, n in months), active, peak if peak[1] else None, streak, longest)


MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def month_name(day: date) -> str:
    return MONTHS[day.month - 1]


def render(summary: Summary) -> str:
    first, last = summary.months[0][0], summary.months[-1][0]
    period = f'{month_name(first)} {first.year} – {month_name(last)} {last.year}'
    peak_month = month_name(summary.peak[0]) if summary.peak else '—'
    peak_count = summary.peak[1] if summary.peak else 0
    current = f'{summary.current_streak} {"day" if summary.current_streak == 1 else "days"}'
    longest = f'{summary.longest_streak} {"day" if summary.longest_streak == 1 else "days"}'
    desc = (f'{period}: {summary.total:,} contributions on {summary.active_days:,} active days. '
            + ', '.join(f'{month_name(day)} {day.year}: {count:,}' for day, count in summary.months)
            + f'. The latest month is in progress. Current streak: {current}. '
            + f'Longest streak: {longest}.')
    baseline = 287
    scale = 103 / max(1, peak_count)
    labels = []
    for i, (month, count) in enumerate(summary.months):
        x = 44 + 50 * i
        height = max(0, round(count * scale))
        partial = i == 11
        if count:
            color = ('fill="#343434" stroke="#d1d1d1" stroke-width="1.5" stroke-dasharray="4 3"'
                     if partial else f'fill="{"#e6e6df" if count == peak_count else "#8b8b85"}"')
            labels.append(f'<rect x="{x - 14}" y="{baseline - height}" width="28" height="{height}" rx="2" {color}/>')
        labels.append(f'<text x="{x}" y="{baseline - height - 9}" text-anchor="middle" font-size="19" fill="#f5f5f0">{count:,}</text>')
        labels.append(f'<text x="{x}" y="314" text-anchor="middle" font-size="18" fill="#bfbfba">{month_name(month)}{"*" if partial else ""}</text>')
    bars = '\n  '.join(labels)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="449" viewBox="0 0 640 449" role="img" aria-labelledby="title desc">
  <title id="title">GitHub activity by month and contribution streaks</title>
  <desc id="desc">{escape(desc)}</desc>
  <rect x="0.5" y="0.5" width="639" height="336" rx="11" fill="#171717" stroke="#454545"/>
  <rect x="0.5" y="349.5" width="313" height="99" rx="11" fill="#171717" stroke="#454545"/>
  <rect x="326.5" y="349.5" width="313" height="99" rx="11" fill="#171717" stroke="#454545"/>
  <g font-family="ui-monospace, 'DejaVu Sans Mono', Consolas, monospace">
    <text x="24" y="38" fill="#f5f5f0" font-size="22" font-weight="bold">$ github activity</text>
    <text x="616" y="37" text-anchor="end" fill="#bfbfba" font-size="17">{period}</text>
    <path d="M24 54h592 M24 148h592" stroke="#454545"/>
    <g fill="#f5f5f0" font-weight="bold" font-size="33">
      <text x="24" y="101">{summary.total:,}</text>
      <text x="240" y="101">{summary.active_days:,}</text>
      <text x="438" y="101">{peak_month}</text>
    </g>
    <g fill="#bfbfba" font-size="18">
      <text x="24" y="127">Contributions</text>
      <text x="240" y="127">Active days</text>
      <text x="438" y="127">Peak month</text>
    </g>
    <path d="M24 234h592" stroke="#494949" stroke-dasharray="2 5"/>
    <path d="M24 {baseline}h592" stroke="#777773"/>
    {bars}
    <g fill="#bfbfba" font-size="21">
      <text x="24" y="383">Current streak</text>
      <text x="350" y="383">Longest streak</text>
    </g>
    <g fill="#f5f5f0" font-weight="bold" font-size="33">
      <text x="24" y="425">{current}</text>
      <text x="350" y="425">{longest}</text>
    </g>
  </g>
</svg>
'''


def fetch_bytes(request: Request) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                data = response.read(1_000_001)
                if len(data) > 1_000_000:
                    raise ValueError('unexpectedly large GitHub response')
                return data
        except HTTPError as error:
            if attempt == 2 or error.code not in {429, 500, 502, 503, 504}:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        sleep(2 ** attempt)
    raise RuntimeError('unreachable retry loop')


def fetch_first_year(login: str) -> int:
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'GitHub-profile-activity-readme/1.0'}
    if token := os.environ.get('GH_TOKEN'):
        headers['Authorization'] = f'Bearer {token}'
    user = json.loads(fetch_bytes(Request(f'https://api.github.com/users/{login}', headers=headers)))
    joined = user.get('created_at') if isinstance(user, dict) else None
    if not isinstance(joined, str):
        raise ValueError('missing GitHub account creation date')
    return date.fromisoformat(joined[:10]).year


def fetch_calendar(login: str, year: int | None) -> str:
    # Historical requests select a calendar year; today's data uses the rolling view.
    suffix = f'?from={year}-01-01' if year is not None else ''
    request = Request(f'https://github.com/users/{login}/contributions{suffix}', headers={
        'Accept-Language': 'en-US', 'User-Agent': 'GitHub-profile-activity-readme/1.0',
    })
    # Never attach the API token or cookies to the visitor-facing calendar.
    return fetch_bytes(request).decode('utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('login', help='GitHub username')
    parser.add_argument('--output', type=Path, default=Path('assets/activity.svg'))
    parser.add_argument('--source-dir', type=Path, help='Offline fixture directory containing YYYY.html calendar pages')
    parser.add_argument('--first-year', type=int, help='Earliest year in the offline fixture directory')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', args.login):
        parser.error('invalid GitHub username')
    if (args.source_dir is None) != (args.first_year is None):
        parser.error('--source-dir and --first-year must be provided together')
    today = datetime.now(timezone.utc).date()
    try:
        if args.source_dir is not None:
            counts = collect_history(args.first_year, today, lambda year:
                                     (args.source_dir / f'{year}.html').read_text(encoding='utf-8'))
        else:
            first_year = fetch_first_year(args.login)
            counts = collect_history(first_year, today, lambda year:
                                     fetch_calendar(args.login, year if year < today.year else None))
        summary = summarize(counts, today)
        svg = render(summary)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not args.output.is_file() or args.output.read_text(encoding='utf-8') != svg:
            args.output.write_text(svg, encoding='utf-8')
    except (ValueError, OSError) as error:
        print(f'Activity refresh failed: {error}', file=sys.stderr)
        return 1
    print(f'{args.login}: {summary.total} contributions, {summary.active_days} active days, '
          f'streak days: {summary.current_streak} current, {summary.longest_streak} longest; '
          f'chart: {window_start(today)} to {today}; history: {min(counts)} to {today} (UTC)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
