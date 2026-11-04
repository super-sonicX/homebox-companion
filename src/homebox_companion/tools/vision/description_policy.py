"""Inventory-first description conventions and deterministic identifier preservation.

The description is the search-result summary in Homebox. Manufacturer, model,
serial and useful part references must also be visible there even when the AI
(or user) populates their dedicated fields.
"""

from __future__ import annotations

import re

MAX_DESCRIPTION_LENGTH = 1000
# Generated headings start a sentence or a line. A suffix in "Compatible Manufacturer:" is authored text.
CLAUSE_START = r"(?:^[ \t]*|(?<=[.;!?])[ \t]+|\r?\n[ \t]*)"
AUTHORED_HEADING = re.compile(CLAUSE_START + r"[^:.;!?\r\n]+:[ \t]*(?=\S|$)")

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
    heading = AUTHORED_HEADING.search(result)
    narrative = result[: heading.start()] if heading else result
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
        own_clause = re.compile(
            rf"{CLAUSE_START}{re.escape(label)}[ \t]*:[ \t]*{re.escape(value)}"
            r"(?:(?<=[.;!?])(?=\s|$)|(?=[.;!?](?:\s|$)|[ \t]*(?:[([]|\r?\n|$)))",
            re.IGNORECASE,
        )
        token = re.compile(rf"(?<![\w./-]){re.escape(value)}(?![\w-]|[./]\w)", re.IGNORECASE)
        if own_clause.search(result) or (not require_label and not value.isdecimal() and token.search(narrative)):
            continue
        phrase = f"{label}: {value}" if value[-1] in ".;!?" else f"{label}: {value}."
        if result and result[-1] not in ".;!?":
            result += "."
        result = f"{result} {phrase}".strip()

    if len(result) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            "Description plus identifiers exceeds 1000 characters. "
            "Shorten the narrative without dropping manufacturer or part details."
        )
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
        previous = ((previous_identifiers or {}).get(key) or "").strip()
        # Match the longest known value first: "A." can start a longer company name.
        known = sorted({value for value in (previous, desired) if value}, key=len, reverse=True)
        alternatives = "|".join([*(re.escape(value) for value in known), r"[^\r\n]*?"])
        clause = re.compile(
            rf"(?P<leading>{CLAUSE_START}){re.escape(label)}[ \t]*:[ \t]*(?P<value>{alternatives})"
            r"(?:(?P<qualifier>[.;!?]?[ \t]*[([])|[.;!?](?=\s|$)|(?<=[.;!?])(?=\s|$)|(?=\r?$))",
            re.IGNORECASE | re.MULTILINE,
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
            same_line = match.string[match.end() :].partition("\n")[0].strip()
            return match["leading"] if "\n" in match["leading"] and same_line else ""

        text = clause.sub(replace_stale, text)
    return text.strip()
