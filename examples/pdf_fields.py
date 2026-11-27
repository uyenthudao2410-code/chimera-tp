"""Extract caller-defined fields and score them against independently labeled pages."""

import json
from pathlib import Path
import re
import unicodedata


def _canonical(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


def read_patterns(path):
    definitions = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError("expected a nonempty JSON object of named field expressions")
    patterns = {}
    for name, expression in definitions.items():
        if not name or not isinstance(expression, str):
            raise ValueError("field names and expressions must be strings")
        pattern = re.compile(expression, re.MULTILINE)
        if pattern.groups != 1:
            raise ValueError(f"{name} must have exactly one capture group")
        patterns[name] = pattern
    return patterns


def extract_fields(text, patterns):
    fields = {}
    for name, regex in patterns.items():
        values = {_canonical(match[1]) for match in regex.finditer(text) if match[1] and match[1].strip()}
        fields[name] = values.pop() if len(values) == 1 else None
    return fields


def evaluate_fields(documents, truth):
    """Count each labeled field once; absent pages/documents stay in the denominator."""
    if not isinstance(truth, dict) or not truth:
        raise ValueError("expected labeled pages indexed by document SHA-256")
    indexed = {(document["sha256"], page["page"]): page for document in documents for page in document["pages"]}
    correct = missing = wrong = 0
    mismatches = []
    for digest, pages in truth.items():
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not isinstance(pages, dict):
            raise ValueError("expected a lowercase SHA-256 and a page object")
        for number, expected in pages.items():
            if not re.fullmatch(r"[1-9][0-9]*", str(number)) or not isinstance(expected, dict) or not expected:
                raise ValueError("each labeled page must have a positive number and expected fields")
            result = indexed.get((digest, int(number)), {}).get("fields", {})
            for name, value in expected.items():
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("ground truth field values must be nonempty strings")
                actual = result.get(name)
                if actual is not None and _canonical(actual) == _canonical(value):
                    correct += 1
                else:
                    if actual is None:
                        missing += 1
                    else:
                        wrong += 1
                    mismatches.append({"sha256": digest, "page": int(number), "field": name,
                                       "expected": value, "actual": actual})
    labels = correct + missing + wrong
    if not labels:
        raise ValueError("no fields were labeled")
    return {"expected": labels, "correct": correct, "missing": missing, "wrong": wrong,
            "exact_match_rate": correct / labels, "mismatches": mismatches}
