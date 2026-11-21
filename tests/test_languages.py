import unittest
from xml.etree import ElementTree as ET

from scripts.languages import PROGRAMMING_LANGUAGES, rank_languages, render


def repo(language, *, fork=False, archived=False, private=False):
    return dict(language=language, fork=fork, archived=archived, private=private)


class LanguageTests(unittest.TestCase):
    def test_tags_rank_actual_programming_languages_by_repo_count_then_name(self):
        repos = [repo('Python'), repo('Python'), repo('JavaScript'), repo('TSQL'),
                 repo('Shell'), repo('Jupyter Notebook'), repo('HTML'), repo('CSS'),
                 repo('Python', private=True), repo('C++', fork=True), repo('Rust', archived=True), repo(None)]
        self.assertEqual(rank_languages(repos), ['Python', 'JavaScript', 'Shell', 'TSQL'])

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
        root = ET.fromstring(render(rank_languages([repo('HTML'), repo(None)])))
        self.assertEqual(root.attrib['height'], '32')
        self.assertIn('No programming language data', ''.join(root.itertext()))
