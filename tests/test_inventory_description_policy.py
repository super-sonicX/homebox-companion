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


def test_short_manufacturer_must_not_match_inside_unrelated_word():
    result = aggregate_description("A voltage regulator.", manufacturer="GE")
    assert "Manufacturer: GE." in result


def test_part_number_must_not_match_longer_part_number():
    result = aggregate_description("Alternative ABC-1234.", model_number="ABC-123")
    assert "Part/model number: ABC-123." in result


def test_custom_numeric_value_must_not_match_another_rating():
    result = aggregate_description("A 12V power supply.", custom_fields={"Current": "2"})
    assert "Current: 2." in result


def test_financial_reference_price_is_excluded_from_description():
    result = aggregate_description(
        "DC-DC converter module.",
        custom_fields={"Supplier Reference": "REF-123", "Reference Price": "£3.00", "Invoice Reference": "INV-99"},
    )
    assert "Supplier Reference: REF-123." in result
    assert "£3.00" not in result
    assert "INV-99" not in result


def test_vision_response_returns_422_instead_of_500_for_overflow():
    from fastapi import HTTPException

    from server.api.tools.vision import aggregate_description_or_422

    with pytest.raises(HTTPException) as error:
        aggregate_description_or_422(
            "A" * 994,
            custom_fields={"Supplier Part Number": "PG4301005"},
        )
    assert error.value.status_code == 422
    assert "1000 characters" in str(error.value.detail)


def test_save_reconciles_superseded_canonical_metadata_without_erasing_prose():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Bumper mounting brackets. Manufacturer: WrongCo. Part/model number: OLD-123."
    cleaned = remove_superseded_generated_identifiers(
        raw,
        manufacturer="RightCo",
        model_number="NEW-456",
        explicitly_updated=frozenset({"manufacturer", "model_number"}),
    )
    assert cleaned == "Bumper mounting brackets."
    result = aggregate_description(cleaned, manufacturer="RightCo", model_number="NEW-456")
    assert "RightCo" in result and "NEW-456" in result
    assert "WrongCo" not in result and "OLD-123" not in result


def test_explicit_clearing_removes_generated_serial_but_not_unrelated_text():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    cleaned = remove_superseded_generated_identifiers(
        "Important technical note. Serial number: BAD-SN-001.",
        serial_number=None,
        explicitly_updated=frozenset({"serial_number"}),
    )
    assert cleaned == "Important technical note."


def test_unspecified_fields_do_not_strip_existing_generated_clauses():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Battery adapter. Manufacturer: ExampleCo."
    assert remove_superseded_generated_identifiers(raw, explicitly_updated=frozenset()) == raw


def test_part_number_matches_sentence_period_but_not_version_suffix():
    assert (
        aggregate_description("Molex connector 50-57-9503.", model_number="50-57-9503") == "Molex connector 50-57-9503."
    )
    result = aggregate_description("Different model ABC-123.4.", model_number="ABC-123")
    assert "Part/model number: ABC-123." in result


@pytest.mark.asyncio
async def test_detection_returns_actionable_422_for_long_custom_identifier(monkeypatch):
    """Exercise the API boundary, not only its helper: overflowing custom data is a 422."""
    import io
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx
    from fastapi import FastAPI
    from PIL import Image

    from homebox_companion.core.config import Settings
    from server.api.tools import vision
    from server.dependencies import get_vision_context, require_llm_configured

    app = FastAPI()
    app.state.settings = Settings()
    app.include_router(vision.router)
    app.dependency_overrides[get_vision_context] = lambda: SimpleNamespace(
        tags=[], field_preferences=None, output_language=None, custom_fields=[], default_tag_id=None
    )
    app.dependency_overrides[require_llm_configured] = lambda: "test-key"
    detected = DetectedItem(name="Bumper bracket", description="x" * 995)
    monkeypatch.setattr(vision, "detect_items_from_bytes", AsyncMock(return_value=[detected]))
    monkeypatch.setattr(vision, "get_custom_fields_dict", lambda item, defs: {"Supplier Part Number": "PG4301005"})
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(image, format="JPEG")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/detect", files={"image": ("part.jpg", image.getvalue(), "image/jpeg")})
    assert response.status_code == 422
    assert "1000 characters" in response.json()["detail"]


def test_save_preserves_user_paragraph_breaks_when_reconciling_metadata():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    original = "First paragraph. Manufacturer: WrongCo.\n\nSecond paragraph is important."
    cleaned = remove_superseded_generated_identifiers(
        original, manufacturer="RightCo", explicitly_updated=frozenset({"manufacturer"})
    )
    assert "\n\nSecond paragraph" in cleaned
    assert "WrongCo" not in cleaned


def test_generated_manufacturer_with_internal_periods_is_preserved_when_unchanged():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    original = "Relay. Manufacturer: Acme Inc. Ltd."
    assert (
        remove_superseded_generated_identifiers(
            original, manufacturer="Acme Inc. Ltd", explicitly_updated=frozenset({"manufacturer"})
        )
        == original
    )


def test_generated_manufacturer_with_internal_periods_is_fully_replaced_or_cleared():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    original = "Relay. Manufacturer: Acme Inc. Ltd. Part/model number: P-1."
    for replacement in ("NewCo", None):
        cleaned = remove_superseded_generated_identifiers(
            original, manufacturer=replacement, explicitly_updated=frozenset({"manufacturer"})
        )
        assert cleaned == "Relay. Part/model number: P-1."
        assert "Ltd" not in cleaned
