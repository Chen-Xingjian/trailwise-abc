"""Read bracketed fact IDs, including grouped references and IDs absent from the release."""
import re

BRACKETS = re.compile(r"\[([^\[\]\n]+)\]")
FACT_ID = re.compile(r"(?<![\w-])(?=[A-Z0-9-]*\d)[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*(?![\w-])")


def citation_ids(text: str) -> set[str]:
    return {fact_id for group in BRACKETS.findall(text) for fact_id in FACT_ID.findall(group)}
