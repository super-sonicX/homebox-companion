"""Inventory-first description conventions and deterministic identifier preservation.

The description is the search-result summary in Homebox. Manufacturer, model,
serial and useful part references must also be visible there even when the AI
(or user) populates their dedicated fields.
"""

from __future__ import annotations

import re

MAX_DESCRIPTION_LENGTH = 1000

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
    for key, value in (custom_fields or {}).items():
        name = key.casefold() if key else ""
        if (
            name
            and value
            and identifier_name.search(name)
            and not financial_name.search(name)
            and not str(value).strip().startswith(("£", "$", "€"))
        ):
            values.append((key, value, True))

    for label, value, require_label in values:
        value = (value or "").strip()
        # A value is already present only if the complete identifier appears.
        # Plain substring checks can mistake "GE" in "voltage", "2" in
        # "12V", or "ABC-123" in "ABC-1234" for an exact match.
        if not value:
            continue
        if require_label:
            # Only an existing *same-field* value may suppress a generated
            # technical specification. The start/punctuation boundary avoids
            # confusing "Voltage" with a longer "Activation Voltage" label.
            token = re.compile(
                rf"(?:^|[.;!?]\s+|\n+){re.escape(label)}\s*:\s*{re.escape(value)}(?=[.;!?](?:\s|$)|$)",
                re.IGNORECASE,
            )
        else:
            token = re.compile(rf"(?<![\w./-]){re.escape(value)}(?![\w-]|[./]\w)", re.IGNORECASE)
        if token.search(result):
            continue
        phrase = f"{label}: {value}."
        if require_label and result and result[-1] not in ".;!?":
            result += "."
        result = f"{result} {phrase}".strip()

    if len(result) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            "Description plus identifiers exceeds 1000 characters. "
            "Shorten the narrative without dropping manufacturer or part details."
        )
    return result


def _split_identifier_and_following_prose(value: str, *, manufacturer: bool) -> tuple[str, str]:
    """Split a generated field from later sentences without discarding prose.

    A machine-appended label has no provenance marker in older descriptions.
    Preserve text after the first sentence boundary, except common company
    legal suffixes such as "Acme Inc. Ltd.". Ambiguous suffixes are retained
    rather than guessing what can safely be deleted.
    """
    for boundary in re.finditer(r"\. +(?=\S)", value):
        before = value[: boundary.start()].strip()
        after = value[boundary.end() :].strip()
        if not manufacturer:
            return before, after
        last_word = before.rsplit(" ", 1)[-1]
        next_word = after.split(" ", 1)[0].strip(".")
        legal_suffixes = {"inc", "ltd", "co", "corp", "llc", "limited"}
        if last_word.casefold() in legal_suffixes and next_word.casefold() in legal_suffixes:
            continue
        # Common dotted prefixes belong to a manufacturer name, not to a
        # separate user sentence (for example "St. Jude" or "Dr. Martens").
        if last_word.casefold() in {"st", "dr", "mr", "mrs", "ms", "prof", "rev"} and next_word[:1].isupper():
            continue
        # Initialled manufacturer names such as "A. O. Smith" are one
        # identifier, not three separate sentences. Avoid extending across
        # ordinary safety notes that start with a capitalised word.
        if len(last_word) == 1 and last_word.isupper() and next_word[:1].isupper():
            if len(next_word) == 1 or ". " in before:
                continue
        # A single initial followed by a single surname is also a valid name.
        if re.fullmatch(r"[A-Z]", before) and re.match(r"^[A-Z][a-z]+(?:\.|$)", after):
            continue
        return before, after
    return value.strip(), ""


def remove_superseded_generated_identifiers(
    description: str | None,
    *,
    manufacturer: str | None = None,
    model_number: str | None = None,
    serial_number: str | None = None,
    explicitly_updated: frozenset[str] = frozenset(),
) -> str:
    """Remove stale *generated* labelled clauses before re-aggregation at save.

    Form submissions may contain a description created by an earlier AI pass,
    then carry a corrected structured field (including explicit null/clear).
    Only canonical clauses generated by Companion are removed; narrative and
    unlabelled identifiers are left alone for the interactive editor to handle.
    Fields omitted by external clients are deliberately not interpreted as
    a request to erase existing narrative content.
    """
    text = (description or "").strip()
    fields = {
        "manufacturer": ("Manufacturer", manufacturer),
        "model_number": ("Part/model number", model_number),
        "serial_number": ("Serial number", serial_number),
    }
    for key, (label, expected) in fields.items():
        if key not in explicitly_updated:
            continue
        # A generated clause ends at the next canonical field or end of text.
        # This avoids splitting manufacturer values such as "Acme Inc. Ltd".
        next_label = r"(?:Manufacturer|Part/model number|Serial number):"
        clause = re.compile(
            rf"(?<!\S){re.escape(label)}:[ \t]*(?P<value>[^\r\n]+?)\.(?=\s+{next_label}|(?:\r?\n){{2,}}|\s*$)",
            re.IGNORECASE,
        )
        # A blank metadata label is not a value; do not read the next paragraph
        # as its content if the user clears the structured field.
        text = re.sub(rf"(?m)(?<!\S){re.escape(label)}:[ \t]*(?=\r?$)", "", text)
        desired = (expected or "").strip().casefold()

        def replace_stale(
            match: re.Match[str], *, desired: str = desired, manufacturer: bool = key == "manufacturer"
        ) -> str:
            """Keep an unchanged value verbatim and retain any user prose after a superseded value."""
            captured_value = match.group("value").strip()
            if desired and (
                captured_value.casefold() == desired or captured_value.casefold().startswith(f"{desired}. ")
            ):
                return match.group(0)
            identifier, following_prose = _split_identifier_and_following_prose(
                captured_value, manufacturer=manufacturer
            )
            if identifier.casefold() == desired:
                return match.group(0)
            # The appended metadata is superseded, but a later user sentence
            # must survive even when it was written on the same line.
            return f"{following_prose}." if following_prose else ""

        text = clause.sub(replace_stale, text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
