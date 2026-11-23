"""Render languages found across owned GitHub repositories."""
import argparse
from collections import Counter
from html import escape
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen


DATA = json.loads(Path(__file__).with_name('language-data.json').read_text(encoding='utf-8'))
PROGRAMMING_LANGUAGES = frozenset(DATA['programming'])
ICONS = DATA['icons']
CODE = 'M8 6 2 12l6 6 1.5-1.5L5 12l4.5-4.5zm8 0-1.5 1.5L19 12l-4.5 4.5L16 18l6-6zm-3.5-2-3 16h2l3-16z'
DATABASE = 'M12 2C7 2 3 4 3 7v10c0 3 4 5 9 5s9-2 9-5V7c0-3-4-5-9-5zm0 2c4 0 7 1.5 7 3s-3 3-7 3-7-1.5-7-3 3-3 7-3zm7 8c0 1.5-3 3-7 3s-7-1.5-7-3v-2c2 1.3 4.5 2 7 2s5-.7 7-2zm0 5c0 1.5-3 3-7 3s-7-1.5-7-3v-2c2 1.3 4.5 2 7 2s5-.7 7-2z'
DISPLAY = {'TSQL': 'T-SQL'}

def rank_languages(repos: list[dict]) -> list[str]:
    counts: Counter[str] = Counter()
    for repo in repos:
        if (not isinstance(repo, dict) or not isinstance(repo.get('languages'), dict)
                or any(type(repo.get(flag)) is not bool for flag in ('fork', 'archived'))):
            raise ValueError('unexpected repositories response')
        if repo['fork'] or repo['archived']:
            continue
        for language in repo['languages']:
            if not isinstance(language, str):
                raise ValueError('unexpected repository language')
            if language in PROGRAMMING_LANGUAGES:
                counts[language] += 1
    return sorted(counts, key=lambda name: (-counts[name], name.casefold(), name))[:7]


def render(languages: list[str]) -> str:
    labels = [DISPLAY.get(language, language) for language in languages]
    description = ('Programming languages by number of repositories: ' + ', '.join(labels)
                   if labels else 'No programming language data')
    tags = []
    width, x, y = 530, 0, 0
    for language, label in zip(languages, labels):
        visible = label if len(label) <= 34 else label[:33] + '…'
        tag_width = 50 + 12 * len(visible)
        if x and x + tag_width > width:
            x, y = 0, y + 46
        icon = DATABASE if language in {'SQL', 'TSQL'} else ICONS.get(language, CODE)
        tags.append(f'''<g data-language="{escape(language, quote=True)}" transform="translate({x} {y})">
      <rect x="0.5" y="0.5" width="{tag_width - 1}" height="37" rx="7" fill="#171717" stroke="#454545"/>
      <path d="{escape(icon, quote=True)}" fill="#d2d2cb" transform="translate(12 8) scale(.92)"/>
      <text x="43" y="25" fill="#f5f5f0">{escape(visible)}</text>
    </g>''')
        x += tag_width + 8
    height = y + 38 if tags else 32
    content = '\n    '.join(tags) or '<text x="0" y="23" fill="#bfbfba">No programming language data</text>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Programming languages</title>
  <desc id="desc">{escape(description)}</desc>
  <g font-family="ui-monospace, 'DejaVu Sans Mono', Consolas, monospace" font-size="19">
    {content}
  </g>
</svg>
'''


def fetch_repos(login: str) -> list[dict]:
    token = os.environ.get('GH_TOKEN')
    if not token:
        raise ValueError('GH_TOKEN is required to read public and private repositories')
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'User-Agent': 'GitHub-profile-language-readme/1.0',
    }
    with urlopen(Request('https://api.github.com/user', headers=headers), timeout=20) as response:
        user = json.load(response)
    if not isinstance(user, dict) or not isinstance(user.get('login'), str) or user['login'].casefold() != login.casefold():
        raise ValueError('authenticated GitHub account does not match requested login')
    repos = []
    for page in range(1, 101):
        request = Request(f'https://api.github.com/user/repos?visibility=all&affiliation=owner&per_page=100&page={page}',
                          headers=headers)
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
            if not isinstance(data, list):
                raise ValueError('unexpected repositories response')
            for repo in data:
                if not isinstance(repo, dict) or not isinstance(repo.get('full_name'), str):
                    raise ValueError('unexpected repositories response')
                if repo.get('fork') or repo.get('archived'):
                    continue
                request = Request(f"https://api.github.com/repos/{repo['full_name']}/languages", headers=headers)
                with urlopen(request, timeout=20) as language_response:
                    languages = json.load(language_response)
                if not isinstance(languages, dict):
                    raise ValueError('unexpected repository languages response')
                repos.append({'fork': False, 'archived': False, 'languages': languages})
            if not re.search(r'\brel="next"', response.headers.get('Link', '')):
                return repos
    raise ValueError('repository pagination exceeded 100 pages')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('login', help='GitHub username')
    parser.add_argument('--output', type=Path, default=Path('assets/languages.svg'))
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', args.login):
        parser.error('invalid GitHub username')
    try:
        languages = rank_languages(fetch_repos(args.login))
        svg = render(languages)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not args.output.is_file() or args.output.read_text(encoding='utf-8') != svg:
            args.output.write_text(svg, encoding='utf-8')
    except (OSError, ValueError):
        print('Language refresh failed; check the token, API access, and response.', file=sys.stderr)
        return 1
    print('Programming languages: ' + (', '.join(DISPLAY.get(lang, lang) for lang in languages) or 'none'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
