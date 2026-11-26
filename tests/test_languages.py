import json
import unittest
from xml.etree import ElementTree as ET

from scripts.languages import PROGRAMMING_LANGUAGES, rank_languages, render


def repo(languages, *, fork=False, archived=False):
    return dict(languages=languages, fork=fork, archived=archived)


class LanguageTests(unittest.TestCase):
    def test_tags_rank_all_programming_languages_by_repo_count_then_name(self):
        repos = [repo({'Python': 1, 'Rust': 1}), repo({'Python': 2}), repo({'JavaScript': 4}),
                 repo({'TSQL': 1}), repo({'Shell': 1}), repo({'HTML': 10}), repo({'Python': 1}, fork=True),
                 repo({'Rust': 1}, archived=True)]
        self.assertEqual(rank_languages(repos), ['Python', 'JavaScript', 'Rust', 'Shell', 'TSQL'])

    def test_language_filter_and_three_letter_lookup(self):
        self.assertTrue({'C++', 'C#', 'R', 'TSQL'} <= PROGRAMMING_LANGUAGES)
        self.assertFalse({'Jupyter Notebook', 'HTML', 'CSS'} & PROGRAMMING_LANGUAGES)

    def test_svg_has_all_labels_icons_and_accessible_description(self):
        root = ET.fromstring(render(['Python', 'C++', 'TSQL', 'Rust']))
        ns = {'s': 'http://www.w3.org/2000/svg'}
        self.assertEqual([t.text for t in root.findall('.//s:text', ns)], ['Python', 'C++', 'T-SQL', 'Rust'])
        self.assertEqual(len(root.findall('.//s:g[@data-language]', ns)), 4)
        for tag in root.findall('.//s:g[@data-language]', ns):
            self.assertIsNotNone(tag.find('.//s:path', ns))
        self.assertIn('Python, C++, T-SQL, Rust', root.findtext('s:desc', default='', namespaces=ns))

    def test_no_code_repos_do_not_render_fabricated_tags(self):
        root = ET.fromstring(render(rank_languages([repo({'HTML': 20}), repo({})])))
        self.assertEqual(root.attrib['height'], '32')
        self.assertIn('No programming language data', ''.join(root.itertext()))

    def test_fetch_repos_paginates_and_reads_only_owned_public_language_maps_without_auth(self):
        from io import BytesIO
        from unittest.mock import patch
        from scripts.languages import fetch_repos

        class Response(BytesIO):
            def __init__(self, payload, link=''):
                super().__init__(json.dumps(payload).encode())
                self.headers = {'Link': link}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        requests = []

        base = 'https://api.github.com'
        listing = f'{base}/users/owner/repos?type=owner&per_page=100&page='

        def entry(full_name, **flags):
            return {'full_name': full_name, 'private': False, 'fork': False, 'archived': False, **flags}

        responses = {
            listing + '1': Response([
                entry('owner/one'), entry('owner/private', private=True),
                entry('owner/fork', fork=True), entry('owner/archived', archived=True),
                entry('other/foreign'),
            ], f'<{listing}2>; rel="next"'),
            listing + '2': Response([entry('owner/two')]),
            f'{base}/repos/owner/one/languages': Response({'Rust': 9, 'Python': 3}),
            f'{base}/repos/owner/two/languages': Response({'Python': 2}),
        }

        def open_request(request, timeout):
            requests.append(request)
            return responses[request.full_url]

        with patch.dict('os.environ', {'GH_TOKEN': ''}), patch('scripts.languages.urlopen', open_request):
            repos = fetch_repos('owner')

        self.assertEqual(len(repos), 2)
        self.assertEqual(rank_languages(repos), ['Python', 'Rust'])
        self.assertCountEqual([r.full_url for r in requests], responses.keys())
        self.assertTrue(all(r.get_header('Authorization') is None for r in requests))
        self.assertNotIn('owner/one', repr(repos))

    def test_fetch_repos_uses_gh_token_when_present(self):
        from io import BytesIO
        from unittest.mock import patch
        from scripts.languages import fetch_repos

        class Response(BytesIO):
            def __init__(self, payload):
                super().__init__(json.dumps(payload).encode())
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        requests = []

        def open_request(request, timeout):
            requests.append(request)
            return Response([])

        with patch.dict('os.environ', {'GH_TOKEN': 'secret-token'}), patch('scripts.languages.urlopen', open_request):
            repos = fetch_repos('owner')

        self.assertEqual(repos, [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer secret-token')
