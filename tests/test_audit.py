import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from piping_claim_audit.audit import PIPE, NOPIPE, audit, claims, evidence

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'


class ClaimsTests(unittest.TestCase):
    def test_all_phrases(self):
        for family, phrases in [('PIPE', PIPE), ('NOPIPE', NOPIPE)]:
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    self.assertEqual([c.family for c in claims(phrase, 'README.md')], [family])

    def test_normalization(self):
        self.assertEqual(claims('PIPE-FRIENDLY', 'x')[0].family, 'PIPE')
        self.assertEqual(claims("doesn't read from stdin", 'x')[0].family, 'NOPIPE')
        self.assertEqual(claims('reads   from\tstdin', 'x')[0].family, 'PIPE')

    def test_negation(self):
        for text in ['not designed for pipelines', 'never works with pipes', 'without piping support', 'no writes stdout']:
            self.assertEqual(claims(text, 'x'), [])
        for text in ['never reads from stdin', 'never writes to stdout', 'not pipe friendly']:
            self.assertEqual([c.family for c in claims(text, 'x')], ['NOPIPE'])

    def test_longest_and_one_family(self):
        self.assertEqual(claims('unix pipe friendly', 'x')[0].phrase, 'unix pipe friendly')
        self.assertEqual([c.family for c in claims('never reads from stdin but writes stdout', 'x')], ['NOPIPE'])
        self.assertEqual(len(claims('reads stdin. no stdin support! writes stdout?', 'x')), 3)

    def test_fences_and_inline(self):
        for fence in ['```', '~~~~']:
            self.assertEqual(claims(f'{fence}\npipe friendly\n{fence}\n', 'x'), [])
        self.assertEqual(len(claims('It is `pipe friendly`.', 'x')), 1)
        self.assertEqual(claims('```text\npipe friendly\n', 'x'), [])

    def test_nouns_and_nonexact(self):
        for text in ['pipe stdin stdout', 'reads from the stdin', 'pipe friendliness', 'xreads stdin', 'supports easy piping']:
            self.assertEqual(claims(text, 'x'), [])


class EvidenceTests(unittest.TestCase):
    def check(self, code, streams):
        self.assertEqual({e.stream for e in evidence(code, 'app.py')}, set(streams))

    def test_input_attributes(self):
        for attr in ['read', 'readline', 'readlines', 'buffer']:
            for suffix in ['', '()']:
                with self.subTest(attr=attr, suffix=suffix):
                    self.check(f'import sys\nsys.stdin.{attr}{suffix}', ['stdin'])

    def test_output_attributes(self):
        for attr in ['write', 'writelines', 'buffer']:
            for suffix in ['', '()']:
                with self.subTest(attr=attr, suffix=suffix):
                    self.check(f'import sys\nsys.stdout.{attr}{suffix}', ['stdout'])

    def test_iteration(self):
        for code in ['for line in sys.stdin: pass', 'iter(sys.stdin)', 'list(sys.stdin)', 'tuple(sys.stdin)', '[x for x in sys.stdin]']:
            with self.subTest(code=code):
                self.check('import sys\n'+code, ['stdin'])

    def test_fileinput(self):
        self.check('import fileinput\nfileinput.input()', ['stdin'])

    def test_argparse(self):
        for expression, stream in [('type=argparse.FileType', 'stdin'), ('type=argparse.FileType()', 'stdin'), ('type=argparse.FileType("r")', 'stdin'), ('type=argparse.FileType("w")', 'stdout'), ('type=argparse.FileType(mode="wb")', 'stdout'), ('default=sys.stdin', 'stdin'), ('default=sys.stdout', 'stdout'), ('type=sys.stdin', 'stdin')]:
            with self.subTest(expression=expression):
                self.check('import argparse, sys\np.add_argument("x", '+expression+')', [stream])

    def test_click(self):
        for code in ['click.File("-")', 'click.get_text_stream("stdin")']:
            self.check('import click\n'+code, ['stdin'])

    def test_print(self):
        for code in ['print("x")', 'print("x", file=sys.stdout)', 'print("x", file=None)']:
            self.check('import sys\n'+code, ['stdout'])

    def test_aliases(self):
        for code, stream in [('import sys as s\ns.stdin.read()', 'stdin'), ('from sys import stdout as out\nout.write("x")', 'stdout'), ('from fileinput import input as lines\nlines()', 'stdin'), ('from argparse import FileType as FT\np.add_argument("x", type=FT("w"))', 'stdout')]:
            self.check(code, [stream])

    def test_shadowing(self):
        for code in ['import sys\nsys = object()\nsys.stdin.read()', 'def print(*args): pass\nprint("x")', 'class print: pass\nprint()', 'import click\nclick = object()\nclick.File("-")', 'import sys\ndef f(sys):\n sys.stdin.read()', 'import fileinput\ndef fileinput(): pass\nfileinput.input()']:
            with self.subTest(code=code):
                self.check(code, [])

    def test_exclusions(self):
        for code in ['input()', 'import logging\nlogging.info("x")', 'import sys\nsys.stderr.write("x")', 'import sys\nprint("x", file=sys.stderr)', 'open("x").read()', 'from pathlib import Path\nPath("x").write_text("y")', 'import subprocess\nsubprocess.Popen("x", stdin=subprocess.PIPE, stdout=subprocess.PIPE)', '# print("x")\nx = "sys.stdin.read()"', 'import click\nclick.echo("x")', 'import sys\nsys.stdout.flush()', 'import click\nclick.File("data")\nclick.get_text_stream("stderr")', 'print("x", file=open("data", "w"))']:
            with self.subTest(code=code):
                self.check(code, [])


class AuditTests(unittest.TestCase):
    def test_named_fixtures(self):
        cases = [('good/pipe', None), ('bad/pipe', ('PIPE', 'HIGH')), ('bad/nopipe', ('NOPIPE', 'HIGH')), ('good/nopipe', None), ('testonly/pipe', ('PIPE', 'MEDIUM')), ('nosource/nopipe', None), ('nosource/pipe', ('PIPE', 'HIGH')), ('guards/fenced', None), ('guards/inline', ('PIPE', 'HIGH'))]
        for folder, expected in cases:
            with self.subTest(folder=folder):
                result = audit(FIXTURES/folder)
                self.assertEqual([(f['family'], f['severity']) for f in result['findings']], [] if expected is None else [expected])
                if expected:
                    self.assertEqual(result['findings'][0]['rule'], 'documented-'+('no-pipe' if expected[0] == 'NOPIPE' else 'pipe')+'-claim-false')

    def test_exclusion_fixtures(self):
        for path in (FIXTURES/'guards/exclusions').iterdir():
            self.assertEqual(audit(path)['findings'], [{'rule': 'documented-pipe-claim-false', 'severity': 'HIGH', 'family': 'PIPE'}])

    def project(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, text in files.items():
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return root

    def test_test_only_negative_and_names(self):
        for name in ['tests/code.py', 'test_app.py', 'app_test.py']:
            root = self.project({'README.md': 'no stdin support', name: 'print("x")'})
            self.assertEqual(audit(root)['findings'][0]['severity'], 'MEDIUM')

    def test_source_exclusions(self):
        for name in ['fixtures/app.py', 'examples/app.py', 'docs/app.py']:
            root = self.project({'README.md': 'pipe friendly', name: 'print("x")'})
            self.assertEqual(audit(root)['evidence'], [])
            self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')

    def test_docs_scope(self):
        root = self.project({'docs/deep/page.md': 'pipe friendly', 'OTHER.md': 'no stdin support', 'nested/README.md': 'no stdin support'})
        self.assertEqual([c['family'] for c in audit(root)['claims']], ['PIPE'])

    def test_ignore(self):
        root = self.project({'README.md': 'pipe friendly', 'docs/deep/page.md': 'no stdin support', 'vendor/a.py': 'print("x")'})
        self.assertEqual(audit(root, ['vendor', 'docs/*'])['findings'][0]['family'], 'PIPE')
        self.assertEqual(audit(root, ['README.md', 'docs'])['findings'], [])
        self.assertEqual(audit(root, ['vendor/*.py', 'docs'])['evidence'], [])

    def test_symlinks(self):
        root = self.project({'real.txt': 'pipe friendly', 'code.txt': 'print("x")'})
        (root/'README.md').symlink_to(root/'real.txt')
        (root/'app.py').symlink_to(root/'code.txt')
        (root/'docs').symlink_to(root, target_is_directory=True)
        self.assertEqual(audit(root)['claims'], [])
        self.assertEqual(audit(root)['evidence'], [])

    def test_env_never_opened(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == '.env':
                raise AssertionError('opened guard')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            self.assertEqual(audit(FIXTURES/'good/pipe')['status'], 'PASS')

    def test_one_finding_per_family_and_either_stream(self):
        root = self.project({'README.md': 'pipe friendly. reads stdin. no stdin support.', 'app.py': 'print("x")'})
        result = audit(root)
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['family'], 'NOPIPE')
        (root/'app.py').write_text('import sys\nsys.stdin.read()')
        self.assertEqual(len(audit(root)['findings']), 1)

    def test_self_audit(self):
        result = audit(ROOT)
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['status'], 'PASS')


class CLITests(unittest.TestCase):
    def run_cli(self, *args, console=False):
        command = ['piping-claim-audit'] if console else [sys.executable, '-m', 'piping_claim_audit']
        return subprocess.run(command+list(map(str, args)), text=True, capture_output=True)

    def test_pass(self):
        result = self.run_cli(FIXTURES/'good/pipe')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'PASS\n')

    def test_bad_exact_json(self):
        result = self.run_cli(FIXTURES/'bad/pipe', '--json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['findings'], [{'rule': 'documented-pipe-claim-false', 'severity': 'HIGH', 'family': 'PIPE'}])

    def test_threshold(self):
        for flags, exit_code in [((), 2), (('--fail-on', 'HIGH'), 0)]:
            result = self.run_cli(FIXTURES/'testonly/pipe', *flags, '--json')
            self.assertEqual(result.returncode, exit_code)
            self.assertEqual(json.loads(result.stdout)['findings'][0]['severity'], 'MEDIUM')
        self.assertEqual(self.run_cli(FIXTURES/'bad/pipe', '--fail-on', 'HIGH').returncode, 2)

    def test_errors(self):
        for args in [('--unknown',), ('--fail-on', 'LOW'), ('/nonexistent-piping-project',), ('--ignore',)]:
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode, 1)
        result = self.run_cli('/nonexistent-piping-project', '--json')
        self.assertEqual(json.loads(result.stdout)['status'], 'ERROR')

    def test_syntax_error(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'app.py').write_text('not valid code !!!')
            self.assertEqual(self.run_cli(temp).returncode, 1)

    def test_unreadable_tree(self):
        from piping_claim_audit.cli import main
        with patch('piping_claim_audit.cli.audit', side_effect=PermissionError('denied')):
            self.assertEqual(main(['.', '--json']), 1)

    def test_verbose(self):
        result = self.run_cli(FIXTURES/'good/pipe', '--verbose')
        self.assertIn('claim README.md:1 PIPE', result.stdout)
        self.assertIn('evidence app.py:', result.stdout)
        self.assertIn('production stdin', result.stdout)

    def test_ignore(self):
        self.assertEqual(self.run_cli(FIXTURES/'bad/pipe', '--ignore', 'README.md', '--ignore', '*.py').returncode, 0)

    def test_entry_points_and_version(self):
        for console in [False, True]:
            self.assertEqual(self.run_cli('--version', console=console).stdout, '0.1.0\n')
            self.assertEqual(self.run_cli(FIXTURES/'good/pipe', console=console).returncode, 0)
            self.assertEqual(self.run_cli(ROOT, console=console).stdout, 'PASS\n')


if __name__ == '__main__':
    unittest.main()
