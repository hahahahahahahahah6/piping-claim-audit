# piping-claim-audit

Version 0.1.0. An offline, read-only static auditor for documented Python
transport claims. It compares Markdown prose with AST evidence, without
executing project code. It never reads .env contents.

Install with `python3 -m pip install .`. Requires Python 3.10 or newer;
the installed application uses only the standard library.

```sh
piping-claim-audit path/to/project
python3 -m piping_claim_audit path/to/project --json
python3 -m piping_claim_audit . --verbose
python3 -m piping_claim_audit . --ignore vendor --ignore 'generated/*' --fail-on HIGH
python3 -m piping_claim_audit --version
```

The root README.md and docs/**/*.md are scanned. Fenced blocks are excluded;
inline code is included. Matching is case insensitive, expands n't to “ not”,
replaces hyphens with spaces, collapses whitespace, and splits sentences at
periods, exclamation marks, question marks, and newlines. Phrases are matched
longest first across both families, with at most one family per sentence.
A remaining no, not, never, or without suppresses a positive match.

Recognized phrases (positive family followed by negative family):

```text
works in a pipeline
works in pipelines
designed for pipelines
fits into a pipeline
fits in a pipeline
reads from standard input
accepts input from stdin
takes stdin as input
reads from stdin
writes to standard output
outputs to standard output
accepts standard input
works with pipes
pipe friendly
supports piping
piping support
can be piped
unix pipe friendly
composable with pipes
input from stdin
output to stdout
reads stdin
writes stdout
stdin input
stdout output
writes to stdout
outputs to stdout

does not read from stdin
never reads from stdin
does not accept stdin
does not write to stdout
never writes to stdout
does not support piping
does not work with pipes
cannot be piped
not pipe friendly
no stdin support
no stdout support
no pipe support
without stdin support
without stdout support
```

Production evidence includes standard stream attribute operations, iteration
on the input stream, fileinput.input, argparse file types and stream defaults,
Click's dash file construction and input text stream retrieval, and builtin
printing. Either input or output evidence can substantiate a positive claim.
Imports and aliases are resolved; local definitions shadow standard names.

Interactive input(), logging, error-stream output, ordinary file operations,
subprocess pipe arguments, comments, strings, click.echo, and flushing alone
are excluded. This is a deliberately limited static analysis, not a proof of
runtime behavior. Syntax and decoding errors are reported as errors.

Production scanning excludes tests, fixtures, docs, examples, and test-named
files. Test evidence is reported separately. Symbolic link files and
directories are skipped. Repeatable --ignore patterns exclude matching paths
or directories from both documentation and source scanning.

There is one finding per contradicted family. The positive rule is
`documented-pipe-claim-false`; the negative rule is
`documented-no-pipe-claim-false`. Production contradictions have HIGH severity;
test-only evidence produces MEDIUM. A positive claim with no source is HIGH;
a negative claim with no source passes. No claim passes.

Exit status is 0 for PASS, 2 for findings, and 1 for errors or invalid flags.
With --fail-on HIGH, MEDIUM-only findings retain their report but exit 0.
--json emits an object with status, findings, claims, and evidence arrays;
--verbose adds claim locations and evidence details to human-readable output.

Development:

```sh
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m build
```

Licensed under the MIT License. See LICENSE.
