"""Check the project subset of ASD-STE100 writing rules."""

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
CONTRACTIONS = re.compile(
    r"\b(?:can't|won't|don't|doesn't|isn't|aren't|it's|we're|you'll|shouldn't)\b", re.I
)
AVOID = re.compile(
    r"\b(?:utilize|utilizes|utilizing|leverage|leverages|seamless|seamlessly|simply|obviously|etc|ensure|ensures|ensuring|via|robust|easy-to-use)\b",
    re.I,
)


def prose_lines(text):
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(("#", "|", "<!--")) or not line.strip():
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"`[^`]*`", "TERM", line)
        line = re.sub(r"https?://\S+", "URL", line)
        yield number, line


def check_text(text, path):
    problems = []
    for number, line in prose_lines(text):
        if re.search(r"[^\x00-\x7f]", line):
            problems.append(f"{path}:{number}: Use English ASCII prose")
        if CONTRACTIONS.search(line):
            problems.append(f"{path}:{number}: Remove the contraction")
        if AVOID.search(line):
            problems.append(f"{path}:{number}: Replace an excluded project word")
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            count = len(WORDS.findall(sentence))
            if count > 20:
                problems.append(
                    f"{path}:{number}: {count} words exceed the project limit of 20"
                )
    return problems


def check(root=ROOT):
    paths = sorted(
        set(root.glob("*.md"))
        | set((root / "docs").rglob("*.md"))
        | set((root / ".github").rglob("*.md"))
    )
    problems = []
    for path in paths:
        problems.extend(
            check_text(path.read_text(encoding="utf-8"), path.relative_to(root))
        )
    for path in sorted((root / "terminx").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                doc = ast.get_docstring(node)
                if doc:
                    problems.extend(
                        check_text(
                            doc,
                            str(path.relative_to(root))
                            + f":docstring:{getattr(node, 'lineno', 1)}",
                        )
                    )
    return paths, problems


def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()
    paths, problems = check()
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(
        f"Document checks passed for {len(paths)} Markdown files and source docstrings."
    )
    print(
        "These checks cover a subset of ASD-STE100. Review word meanings and parts of speech separately."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
