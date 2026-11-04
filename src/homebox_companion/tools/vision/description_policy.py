"""Inventory-first description conventions and deterministic identifier preservation.

The description is the search-result summary in Homebox. Manufacturer, model,
serial and useful part references must also be visible there even when the AI
(or user) populates their dedicated fields.
"""

from __future__ import annotations

import re
from itertools import chain

MAX_DESCRIPTION_LENGTH = 1000
DESCRIPTION_OVERFLOW = (
    "Description plus identifiers exceeds 1000 characters. "
    "Shorten the narrative without dropping manufacturer or part details."
)
# One Unicode space separator (Zs) or tab, excluding line breaks.
HSPACE = r"[\t \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]"
LINE_CHARACTERS = r"\r\n\v\f\u0085\u2028\u2029"
LINE_BREAK = rf"(?:\r\n|[{LINE_CHARACTERS}])"
SAME_LINE_CONTENT = re.compile(rf"{HSPACE}*\S")
# Generated headings start a sentence or a line. Commas separate prose cues and notes, not generated headings.
CLAUSE_START = rf"(?:^{HSPACE}*|(?<=[.;!?]){HSPACE}+|{LINE_BREAK}{HSPACE}*)"
TECHNICAL_CLAUSE_START = rf"(?:,{HSPACE}*|{CLAUSE_START})"

INVENTORY_DESCRIPTION_GUIDANCE = (
    "INVENTORY DESCRIPTION POLICY (mandatory, even when field preferences differ):\n"
    "- Write a concise functional description: what the item IS, what it DOES, "
    "and defining technical specifications relevant to finding or selecting it.\n"
    "- Repeat useful manufacturer/brand, exact model and manufacturer part number "
    "in the description, even when also extracting them into separate fields.\n"
    "- Preserve essential ratings, dimensions, interfaces, compatibility and included "
    "accessories when known. Do not guess unseen or unconfirmed specifications.\n"
    "- Do NOT narrate the photograph or packaging (e.g. visible box, transparent bag, "
    "tatty packaging, label position, colour of the carpet). Mention condition only "
    "if it affects function, completeness, safety, or the inventory item actually IS packaging.\n"
    "- Keep prices, routine shipping history and seller information in their proper "
    "fields/notes, not the short description, unless essential for identification.\n"
    "- Description must be useful by itself in a Homebox list/search response; "
    "do not require a second item-detail fetch to identify the product.\n"
)


# The review editor uses these same cues when correcting prose.
# Unicode Space_Separator (Zs) plus tab, deliberately excluding line separators.
HORIZONTAL_SPACING = re.compile(rf"{HSPACE}+")
HEADING_MARKS = re.compile(rf":|{LINE_BREAK}|(?<=[,.;!?])(?={HSPACE})")
HISTORICAL_HEADING = re.compile(r"^(?:previous|original|former|compatible|alternative|historical|replacement)\b", re.I)
COMPATIBILITY_REFERENCE = re.compile(
    r"\b(?:(?:in)?compatible with|works with|for use with|replacement for|fits)\b", re.I
)
MAKER_ATTRIBUTION = re.compile(r"\b(?:made|manufactured) by[ \t]*\Z", re.I)
FOR_TARGET = re.compile(r"\bfor\b(?! (?:example|instance)\b)", re.I)
NARRATIVE_FIELD_CUES = {
    "Manufacturer": re.compile(r"\b(?:manufacturer|brand(?: name)?|made by|manufactured by)[ \t]*[#:=]?[ \t]*\Z", re.I),
    "Part/model number": re.compile(
        r"\b(?:(?:model|part)(?:[ \t]+(?:number|no\.?))?|mpn|p/n)[ \t]*[#:=]?[ \t]*\Z", re.I
    ),
    "Serial number": re.compile(r"\b(?:serial(?:[ \t]+(?:number|no\.?))?|s/n)[ \t]*[#:=]?[ \t]*\Z", re.I),
}


def _narrative_prefix(text: str, custom_fields: dict[str, str] | None) -> str:
    """Separate narrative identity cues from named fields and authored notes."""
    if ":" not in text:
        return text
    identities = {label.casefold() for label in NARRATIVE_FIELD_CUES}
    candidates = []
    for leading in re.finditer(TECHNICAL_CLAUSE_START, text):
        colon = text.find(":", leading.end())
        if colon >= 0:
            label = text[leading.end() : colon].strip().casefold()
            if not (leading[0].startswith(",") and label in identities):
                candidates.append((leading.start(), label))
    # Retain only names present in the bounded description, regardless of the size of the input mapping.
    wanted = {label for _, label in candidates}
    protected = identities | {
        label for key in custom_fields or {} if len(key) <= len(text) and (label := key.strip().casefold()) in wanted
    }
    for offset, label in candidates:
        if label in protected:
            text = text[:offset]
            break
    start = 0
    for mark in HEADING_MARKS.finditer(text):
        if mark[0] == ":":
            heading = HORIZONTAL_SPACING.sub(" ", text[start : mark.start()].strip())
            if heading and (
                HISTORICAL_HEADING.match(heading)
                or not any(pattern.search(heading) for pattern in NARRATIVE_FIELD_CUES.values())
            ):
                return text[:start]
        start = mark.end()
    return text


SENTENCE_END = re.compile(rf"[;!?]|{LINE_BREAK}|\.(?=\s|$)")
ABBREVIATION = re.compile(r"\b(?:[a-z]|approx|no|nos|ref|rev|fig|inc|ltd|corp|co|dr|st|mr|mrs|ms|dia)\Z", re.I)


def _sentence_prefix(before: str) -> str:
    """Locate the current sentence without splitting decimal measurements, dotted names or abbreviations."""
    start = 0
    for end in SENTENCE_END.finditer(before):
        if end[0] != "." or not ABBREVIATION.search(before[start : end.start()]):
            start = end.end()
    return before[start:]


def _narrative_has_identifier(narrative: str, value: str, label: str) -> bool:
    """Prefer the field named in the prose when an identifier could describe multiple fields."""
    token = re.compile(rf"(?<![\w./-]){re.escape(value)}(?![\w-]|[./]\w)", re.IGNORECASE)
    distinctive = not value.isdecimal() and len(value) >= (2 if label == "Manufacturer" else 3)
    for match in token.finditer(narrative):
        before = HORIZONTAL_SPACING.sub(" ", narrative[: match.start()])
        cue = next((field for field, pattern in NARRATIVE_FIELD_CUES.items() if pattern.search(before)), None)
        sentence = _sentence_prefix(before)
        if COMPATIBILITY_REFERENCE.search(sentence) or FOR_TARGET.search(sentence):
            _, comma, field_prefix = sentence.rpartition(",")
            separate_field = comma and cue and NARRATIVE_FIELD_CUES[cue].fullmatch(field_prefix.strip())
            if not separate_field and not (cue == "Manufacturer" and MAKER_ATTRIBUTION.search(sentence)):
                continue
        if cue == label or (cue is None and distinctive):
            return True
    return False


def aggregate_description(
    description: str | None,
    *,
    manufacturer: str | None = None,
    model_number: str | None = None,
    serial_number: str | None = None,
    custom_fields: dict[str, str] | None = None,
) -> str:
    """Repeat identifying fields in a concise description without duplicating values.

    Uncertain model output is not inferred here: only *explicitly supplied*
    metadata values are appended. The LLM still owns the semantic description.
    Never truncate or discard a part number: overflow is raised to the caller.
    """
    result = (description or "").strip()
    if len(result) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(DESCRIPTION_OVERFLOW)
    narrative = _narrative_prefix(result, custom_fields)
    # Custom technical specifications require field-specific deduplication.
    # A "12" that appears in Voltage must not suppress Current: 12.
    values = [
        ("Manufacturer", manufacturer, False),
        ("Part/model number", model_number, False),
        ("Serial number", serial_number, False),
    ]
    relevant_custom_identifiers = (
        "part number",
        "part no",
        "mpn",
        "sku",
        "reference",
        "voltage",
        "current",
        "power rating",
        "wattage",
        "capacitance",
        "resistance",
        "dimensions",
        "diameter",
        "pitch",
        "connector type",
        "compatibility",
        "capacity",
    )
    identifier_name = re.compile(
        rf"(?<!\w)(?:{'|'.join(re.escape(term) for term in relevant_custom_identifiers)})(?!\w)",
        re.IGNORECASE,
    )
    financial_name = re.compile(
        r"(?<!\w)(?:price|cost|amount|payment|invoice|receipt|shipping|postage|tax|vat|discount)(?!\w)",
        re.IGNORECASE,
    )
    custom_identifiers = (
        (key, value, True)
        for key, value in (custom_fields or {}).items()
        if key
        and value
        and identifier_name.search(key)
        and not financial_name.search(key)
        and not value.lstrip().startswith(("£", "$", "€"))
    )
    for label, value, require_label in chain(values, custom_identifiers):
        value = (value or "").strip()
        # A value is already present only if the complete identifier appears.
        # Plain substring checks can mistake "GE" in "voltage", "2" in
        # "12V", or "ABC-123" in "ABC-1234" for an exact match.
        if not value:
            continue
        if len(value) > MAX_DESCRIPTION_LENGTH or (
            require_label and len(label) + 1 + len(value) > MAX_DESCRIPTION_LENGTH
        ):
            raise ValueError(DESCRIPTION_OVERFLOW)
        clause_start = TECHNICAL_CLAUSE_START if require_label else CLAUSE_START
        own_clause = re.compile(
            rf"{clause_start}{re.escape(label)}{HSPACE}*:{HSPACE}*{re.escape(value)}"
            rf"(?:(?<=[.;!?])(?=\s|$)|(?=[,.;!?](?:\s|$)|{HSPACE}*(?:[([]|{LINE_BREAK}|$)))",
            re.IGNORECASE,
        )
        if own_clause.search(result) or (not require_label and _narrative_has_identifier(narrative, value, label)):
            continue
        phrase = f"{label}: {value}" if value[-1] in ".;!?" else f"{label}: {value}."
        if result and result[-1] not in ".;!?":
            result += "."
        result = f"{result} {phrase}".strip()

        if len(result) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(DESCRIPTION_OVERFLOW)
    return result


def remove_superseded_generated_identifiers(
    description: str | None,
    *,
    manufacturer: str | None = None,
    model_number: str | None = None,
    serial_number: str | None = None,
    explicitly_updated: frozenset[str] = frozenset(),
    previous_identifiers: dict[str, str | None] | None = None,
) -> str:
    """Remove stale *generated* labelled clauses before re-aggregation at save.

    Form submissions may contain a description created by an earlier AI pass,
    then carry a corrected structured field (including explicit null/clear).
    Only canonical clauses generated by Companion are removed; narrative and
    unlabelled identifiers are left alone for the interactive editor to handle.
    Fields omitted by external clients are deliberately not interpreted as
    a request to erase existing narrative content.
    """
    originals = previous_identifiers or {}
    if any(value and len(value) > 255 for value in originals.values()):
        raise ValueError("Previous identifiers must be at most 255 characters.")
    text = (description or "").strip()
    fields = {
        "manufacturer": ("Manufacturer", manufacturer),
        "model_number": ("Part/model number", model_number),
        "serial_number": ("Serial number", serial_number),
    }
    for key, (label, expected) in fields.items():
        if key not in explicitly_updated:
            continue
        desired = (expected or "").strip()
        previous = (originals.get(key) or "").strip()
        # The review form also submits untouched identifiers, including explicit nulls.
        if key in originals and previous == desired:
            continue
        # Match the longest known value first: "A." can start a longer company name.
        known = sorted({value for value in (previous, desired) if value}, key=len, reverse=True)
        alternatives = "|".join([*(re.escape(value) for value in known), rf"[^{LINE_CHARACTERS}]*?"])
        clause = re.compile(
            rf"(?P<leading>{CLAUSE_START}){re.escape(label)}{HSPACE}*:{HSPACE}*(?P<value>{alternatives})"
            rf"(?:(?P<qualifier>[.;!?]?{HSPACE}*[([])|[,.;!?](?=\s|$)|(?<=[.;!?])(?=\s|$)|(?={LINE_BREAK}|\Z))",
            re.IGNORECASE,
        )

        def replace_stale(
            match: re.Match[str],
            *,
            previous: str = previous,
            desired: str = desired,
            field: str = key,
            label: str = label,
        ) -> str:
            """Remove just the matched value and delimiter, leaving later sentences untouched."""
            value = match["value"].strip()
            if value and value.casefold() == desired.casefold():
                return match[0]
            if value and (not previous or value.casefold() != previous.casefold()):
                raise ValueError(
                    f"Cannot safely separate the previous {field} from the description. "
                    "Correct the labelled text or supply the matching previous_identifiers value."
                )
            if match["qualifier"]:
                # Keep authored annotations with the identity they describe, even after a correction.
                leading = match["leading"]
                return f"{leading}Previous {label.lower()}{match[0][len(leading) + len(label) :]}"
            if re.search(LINE_BREAK, match["leading"]) and SAME_LINE_CONTENT.match(match.string, match.end()):
                return match["leading"]
            return ""

        text = clause.sub(replace_stale, text)
    return text.strip()
