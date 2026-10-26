"""Command line interface."""
import argparse
import json
import sys
from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def main(argv=None):
    parser = Parser(description="Audit documented transport claims without executing project code.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ignore", action="append", default=[], metavar="GLOB")
    parser.add_argument("--fail-on", choices=["HIGH"])
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError, SyntaxError) as error:
        if args.json:
            print(json.dumps({"status": "ERROR", "error": str(error)}))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result["status"])
        for finding in result["findings"]:
            print(f"{finding['severity']} {finding['rule']}")
        if args.verbose:
            for claim in result["claims"]:
                print(f"claim {claim['path']}:{claim['line']} {claim['family']} {claim['phrase']}")
            for item in result["evidence"]:
                origin = "test" if item["test"] else "production"
                print(f"evidence {item['path']}:{item['line']} {origin} {item['stream']} {item['detail']}")
    return 2 if any(args.fail_on is None or f["severity"] == "HIGH" for f in result["findings"]) else 0
