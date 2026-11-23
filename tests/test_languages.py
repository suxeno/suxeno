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

    def test_owner_private_repository_languages_are_included(self):
        self.assertEqual(rank_languages([repo({'Python': 1})]), ['Python'])

    def test_fetch_repos_paginates_and_fetches_every_repository_language_map(self):
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

        def open_request(request, timeout):
            requests.append(request)
            if request.full_url == 'https://api.github.com/user':
                return Response({'login': 'owner'})
            if '/user/repos?' in request.full_url:
                page = len([r for r in requests if '/user/repos?' in r.full_url])
                if page == 1:
                    return Response([{'full_name': 'owner/one', 'fork': False, 'archived': False}],
                                    '<https://api.github.com/user/repos?page=2>; rel="next"')
                return Response([{'full_name': 'owner/two', 'fork': False, 'archived': False}])
            return Response({'Rust': 9, 'Python': 3})

        with patch.dict('os.environ', {'GH_TOKEN': 'test-token'}), patch('scripts.languages.urlopen', open_request):
            repos = fetch_repos('owner')

        self.assertEqual(len(repos), 2)
        self.assertEqual(rank_languages(repos), ['Python', 'Rust'])
        self.assertEqual(len(requests), 5)
        self.assertTrue(all(r.get_header('Authorization') == 'Bearer test-token' for r in requests))
        self.assertNotIn('owner/one', repr(requests))
