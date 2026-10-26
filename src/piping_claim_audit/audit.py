"""Claim extraction and static evidence collection; no project code is run."""
import ast
from dataclasses import asdict, dataclass
import fnmatch
import os
from pathlib import Path
import re

PIPE = (
    "works in a pipeline", "works in pipelines", "designed for pipelines",
    "fits into a pipeline", "fits in a pipeline", "reads from standard input",
    "accepts input from stdin", "takes stdin as input", "reads from stdin",
    "writes to standard output", "outputs to standard output", "accepts standard input",
    "works with pipes", "pipe friendly", "supports piping", "piping support",
    "can be piped", "unix pipe friendly", "composable with pipes", "input from stdin",
    "output to stdout", "reads stdin", "writes stdout", "stdin input", "stdout output",
    "writes to stdout", "outputs to stdout",
)
NOPIPE = (
    "does not read from stdin", "never reads from stdin", "does not accept stdin",
    "does not write to stdout", "never writes to stdout", "does not support piping",
    "does not work with pipes", "cannot be piped", "not pipe friendly",
    "no stdin support", "no stdout support", "no pipe support",
    "without stdin support", "without stdout support",
)
PHRASES = sorted([(p, "PIPE") for p in PIPE] + [(p, "NOPIPE") for p in NOPIPE],
                 key=lambda item: -len(item[0]))


@dataclass
class Claim:
    family: str
    path: str
    line: int
    phrase: str


@dataclass
class Evidence:
    stream: str
    path: str
    line: int
    detail: str
    test: bool = False


@dataclass
class Finding:
    rule: str
    severity: str
    family: str


def claims(text, path):
    result = []
    fence = None
    for lineno, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not line[marker.end():].strip():
                fence = None
            continue
        if fence:
            continue
        for sentence in re.split(r"[.!?\n]+", line):
            normalized = " ".join(sentence.lower().replace("n't", " not").replace("-", " ").split())
            for phrase, family in PHRASES:
                match = re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized)
                if match:
                    remainder = normalized[:match.start()] + " " + normalized[match.end():]
                    if family == "NOPIPE" or not re.search(r"\b(no|not|never|without)\b", remainder):
                        result.append(Claim(family, path, lineno, phrase))
                    break
    return result


def evidence(text, path, test=False):
    tree = ast.parse(text, filename=path)
    aliases = {}
    shadowed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split('.')[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadowed.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadowed.add(node.id)
        elif isinstance(node, ast.arg):
            shadowed.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            shadowed.add(node.name)

    def name(node):
        if isinstance(node, ast.Name):
            if node.id in shadowed:
                return ""
            return aliases.get(node.id, node.id if node.id in {"print", "iter", "list", "tuple"} else "")
        if isinstance(node, ast.Attribute):
            base = name(node.value)
            return f"{base}.{node.attr}" if base else ""
        return ""

    found = []
    def add(node, stream, detail):
        found.append(Evidence(stream, path, node.lineno, detail, test))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            base = name(node.value)
            if base == "sys.stdin" and node.attr in {"read", "readline", "readlines", "buffer"}:
                add(node, "stdin", base + "." + node.attr)
            if base == "sys.stdout" and node.attr in {"write", "writelines", "buffer"}:
                add(node, "stdout", base + "." + node.attr)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)) and name(node.iter) == "sys.stdin":
            add(node.iter, "stdin", "iteration")
        if not isinstance(node, ast.Call):
            continue
        func = name(node.func)
        if func in {"iter", "list", "tuple"} and node.args and name(node.args[0]) == "sys.stdin":
            add(node, "stdin", func)
        if func == "fileinput.input":
            add(node, "stdin", func)
        if func == "click.File" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "-":
            add(node, "stdin", func)
        if func == "click.get_text_stream" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "stdin":
            add(node, "stdin", func)
        if func == "print":
            destinations = [kw.value for kw in node.keywords if kw.arg == "file"]
            if not destinations or any(name(dest) == "sys.stdout" or isinstance(dest, ast.Constant) and dest.value is None for dest in destinations):
                add(node, "stdout", "print")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            for kw in node.keywords:
                if kw.arg == "default" and name(kw.value) in {"sys.stdin", "sys.stdout"}:
                    add(node, name(kw.value).split('.')[-1], "argument default")
                if kw.arg != "type":
                    continue
                if name(kw.value) in {"sys.stdin", "argparse.FileType"}:
                    add(node, "stdin", "argument type")
                if isinstance(kw.value, ast.Call) and name(kw.value.func) == "argparse.FileType":
                    modes = list(kw.value.args) + [k.value for k in kw.value.keywords if k.arg == "mode"]
                    output = any(isinstance(m, ast.Constant) and isinstance(m.value, str) and "w" in m.value for m in modes)
                    add(node, "stdout" if output else "stdin", "argument FileType")
    return found


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise OSError(f"not a readable project directory: {root}")
    all_claims, all_evidence = [], []
    def ignored(rel):
        parts = rel.split('/')
        return any(fnmatch.fnmatch(rel, pattern.rstrip('/')) or
                   any(fnmatch.fnmatch('/'.join(parts[:i]), pattern.rstrip('/')) for i in range(1, len(parts) + 1))
                   for pattern in ignore)
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=walk_error, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink() and not ignored((base / d).relative_to(root).as_posix()))
        for filename in sorted(files):
            path = base / filename
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or ignored(rel):
                continue
            parts = Path(rel).parts
            is_doc = rel == "README.md" or parts[0] == "docs" and path.suffix == ".md"
            is_test = "tests" in parts[:-1] or filename.startswith("test_") or filename.endswith("_test.py")
            excluded = bool(set(parts[:-1]) & {"fixtures", "docs", "examples"})
            if is_doc:
                all_claims.extend(claims(path.read_text(encoding="utf-8"), rel))
            if path.suffix == ".py" and not excluded:
                all_evidence.extend(evidence(path.read_text(encoding="utf-8"), rel, is_test))
    production = [e for e in all_evidence if not e.test]
    tests = [e for e in all_evidence if e.test]
    findings = []
    families = {c.family for c in all_claims}
    for family, rule in [("PIPE", "documented-pipe-claim-false"), ("NOPIPE", "documented-no-pipe-claim-false")]:
        if family not in families:
            continue
        severity = None
        if family == "PIPE" and not production:
            severity = "MEDIUM" if tests else "HIGH"
        elif family == "NOPIPE":
            severity = "HIGH" if production else "MEDIUM" if tests else None
        if severity:
            findings.append(Finding(rule, severity, family))
    return {"status": "FAIL" if findings else "PASS", "findings": [asdict(f) for f in findings],
            "claims": [asdict(c) for c in all_claims], "evidence": [asdict(e) for e in all_evidence]}
