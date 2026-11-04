# Inventory-first item descriptions

**Status:** implemented in Homebox Companion (AI vision and item creation).

Homebox list/search responses contain item name and description but do **not** include all structured metadata, such as manufacturer or model number. The description must therefore be independently useful for finding and selecting an item.

## Required behaviour

1. Describe **what the item is and does** in one concise, meaningful opening sentence; include the specifications most useful for selecting a compatible part (ratings, dimensions, interfaces, fitment).
2. **Include manufacturer, exact part number/model, and other significant identifying references in Description**, even where duplicated into dedicated Manufacturer, Model Number or custom fields.
3. Preserve the structured values as well. A description is not a substitute for correct metadata.
4. Do not narrate the photograph, box condition, background, visible packaging or camera angle. Mention packaging where the **item itself is an empty product box**, or mention damage only when it affects usability, safety or completeness.
5. Keep financial values, shipping information and routine provenance in appropriate fields or Notes unless they are essential for identifying the item.
6. Do not guess unclear part numbers or technical ratings. Preserve uncertainty explicitly.
7. Item count belongs in Quantity. Describe a kit's contents where needed to understand what is included.

## How enforcement works

- Vision **detection**, **advanced item analysis**, and **correction** prompts include these requirements irrespective of custom field-instruction overrides.
- The validated AI output repeats explicit Manufacturer, Model Number and Serial Number in Description if not already present (idempotently).
- Detection/analysis responses also repeat populated custom fields that represent identifiers or useful technical specifications (part numbers, MPNs, SKUs, voltage, current, power ratings, dimensions, capacity and compatibility).
- The **create-item endpoint** re-aggregates the final values after any edits made in the Companion UI, so changing Manufacturer/Model Number does not leave the Description behind.
- The review form retains the original structured identifiers. To remove or replace an existing labelled value, an API client can provide the exact old value in the optional `previous_identifiers` object. Companion returns a per-item validation error when it cannot distinguish a name from a following sentence safely. The original identifiers are used only by Companion.
- A description exceeding Homebox's 1,000-character maximum after aggregation fails rather than silently truncating an identifier.

## Example

**Item:** `Front Bumper Bracket Set Peugeot 308 2017–2021 RH + LH PG4301005`

**Description:** `Peugeot 308 replacement front bumper mounting brackets, left and right. Manufacturer/reference: PG4301005; confirm model-year and trim compatibility.`

**Model Number:** `PG4301005`

Don't write: `Black plastic brackets shown in a clear bag. The packaging is creased.`

This policy applies to **new or edited Companion items**. It does not retroactively rewrite existing Homebox inventory. The broader category-specific naming convention is a separate document.
