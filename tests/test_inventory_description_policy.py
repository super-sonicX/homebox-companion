"""Descriptions must stand alone in Homebox search results."""

import pytest

from homebox_companion.tools.vision.description_policy import (
    INVENTORY_DESCRIPTION_GUIDANCE,
    aggregate_description,
)
from homebox_companion.tools.vision.models import DetectedItem
from homebox_companion.tools.vision.prompts import (
    build_analysis_system_prompt,
    build_detection_system_prompt,
    build_multi_image_system_prompt,
)


def test_aggregates_manufacturer_and_part_number_without_sacrificing_structured_fields():
    item = DetectedItem.model_validate(
        {
            "name": "Front Bumper Bracket Peugeot 308",
            "description": "Peugeot 308 front bumper mounting brackets for both sides.",
            "manufacturer": "Peugeot",
            "modelNumber": "PG4301005",
        }
    )
    assert item.manufacturer == "Peugeot"
    assert item.model_number == "PG4301005"
    assert "Peugeot" in item.description
    assert "Part/model number: PG4301005." in item.description
    assert "PG4301005" in item.model_dump(by_alias=True)["description"]


def test_idempotent_if_manufacturer_and_part_number_already_present():
    description = "Molex connector, part number 50-57-9503."
    assert aggregate_description(description, manufacturer="Molex", model_number="50-57-9503") == description


def test_serial_number_is_also_retrievable_without_full_detail_fetch():
    item = DetectedItem(name="Multimeter", description="Portable digital multimeter.", serialNumber="SN-2026-A1")
    assert "Serial number: SN-2026-A1." in item.description


def test_relevant_custom_part_numbers_are_preserved_but_price_is_not():
    result = aggregate_description(
        "RCA plug for audio cables.",
        custom_fields={
            "Supplier Part Number": "NYS352BG",
            "Voltage rating": "12V",
            "Purchase price": "£3.00",
        },
    )
    assert "NYS352BG" in result
    assert "Voltage rating: 12V." in result
    assert "£3.00" not in result


def test_long_description_fails_instead_of_truncating_identifier():
    with pytest.raises(ValueError, match="1000 characters"):
        aggregate_description("A" * 995, model_number="PG4301005")


@pytest.mark.parametrize(
    "builder,kwargs",
    [
        (build_detection_system_prompt, {}),
        (build_multi_image_system_prompt, {}),
        (build_analysis_system_prompt, {"item_name": "Bumper brackets", "item_description": ""}),
    ],
)
def test_all_vision_prompts_enforce_inventory_first_policy(builder, kwargs):
    prompt = builder(**kwargs)
    assert "INVENTORY DESCRIPTION POLICY" in prompt
    assert "Do NOT narrate the photograph or packaging" in prompt
    assert "manufacturer/brand" in prompt


def test_persistent_description_preference_cannot_undo_mandatory_guidance():
    prompt = build_detection_system_prompt(field_preferences={"description": "Describe every scratch on the box."})
    assert "Describe every scratch on the box." in prompt
    assert INVENTORY_DESCRIPTION_GUIDANCE.strip() in prompt
