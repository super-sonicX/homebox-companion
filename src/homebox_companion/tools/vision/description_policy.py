"""Inventory-first description conventions and deterministic identifier preservation.

The description is the search-result summary in Homebox. Manufacturer, model,
serial and useful part references must also be visible there even when the AI
(or user) populates their dedicated fields.
"""

from __future__ import annotations

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
    values = [
        ("Manufacturer", manufacturer),
        ("Part/model number", model_number),
        ("Serial number", serial_number),
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
    for key, value in (custom_fields or {}).items():
        if key and value and any(term in key.casefold() for term in relevant_custom_identifiers):
            values.append((key, value))

    for label, value in values:
        value = (value or "").strip()
        if not value or value.casefold() in result.casefold():
            continue
        phrase = f"{label}: {value}."
        result = f"{result.rstrip()} {phrase}".strip() if result else phrase

    if len(result) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            "Description plus identifiers exceeds 1000 characters. "
            "Shorten the narrative without dropping manufacturer or part details."
        )
    return result
