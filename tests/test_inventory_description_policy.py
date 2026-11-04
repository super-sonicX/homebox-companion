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
    # The Pydantic transport model must not aggregate identifiers before the
    # API can convert overflows into an actionable validation response.
    assert item.description == "Peugeot 308 front bumper mounting brackets for both sides."
    display = aggregate_description(item.description, manufacturer=item.manufacturer, model_number=item.model_number)
    assert "Part/model number: PG4301005." in display
    assert item.model_dump(by_alias=True)["description"] == item.description


def test_idempotent_if_manufacturer_and_part_number_already_present():
    description = "Molex connector, part number 50-57-9503."
    assert aggregate_description(description, manufacturer="Molex", model_number="50-57-9503") == description


def test_serial_number_is_also_retrievable_without_full_detail_fetch():
    item = DetectedItem(name="Multimeter", description="Portable digital multimeter.", serialNumber="SN-2026-A1")
    display = aggregate_description(item.description, serial_number=item.serial_number)
    assert "Serial number: SN-2026-A1." in display


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
    """Rebuild the search summary from the corrected structured fields while retaining the item narrative."""
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Bumper mounting brackets. Manufacturer: WrongCo. Part/model number: OLD-123."
    cleaned = remove_superseded_generated_identifiers(
        raw,
        manufacturer="RightCo",
        model_number="NEW-456",
        previous_identifiers={"manufacturer": "WrongCo", "model_number": "OLD-123"},
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
        previous_identifiers={"serial_number": "BAD-SN-001"},
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
@pytest.mark.parametrize("overflow_source", ["custom", "manufacturer"])
async def test_detection_returns_actionable_422_for_long_identifiers(monkeypatch, overflow_source):
    """Actual HTTP path reports a guarded error, whether overflow is from AI metadata or a custom field."""
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
    from homebox_companion.tools.vision.models import get_items_adapter

    raw = {"name": "Bumper bracket", "description": "x" * 995}
    if overflow_source == "manufacturer":
        raw["manufacturer"] = "ExampleCo"
    # This exercises the same Pydantic transport adapter used after LLM
    # responses; its validation must succeed before the guarded API boundary.
    detected = get_items_adapter(None).validate_python([raw])[0]
    monkeypatch.setattr(vision, "detect_items_from_bytes", AsyncMock(return_value=[detected]))
    custom = {"Supplier Part Number": "PG4301005"} if overflow_source == "custom" else None
    monkeypatch.setattr(vision, "get_custom_fields_dict", lambda item, defs: custom)
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
        original,
        manufacturer="RightCo",
        previous_identifiers={"manufacturer": "WrongCo"},
        explicitly_updated=frozenset({"manufacturer"}),
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
    """A dotted legal suffix must leave the description together with its old manufacturer."""
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    original = "Relay. Manufacturer: Acme Inc. Ltd. Part/model number: P-1."
    for replacement in ("NewCo", None):
        cleaned = remove_superseded_generated_identifiers(
            original,
            manufacturer=replacement,
            previous_identifiers={"manufacturer": "Acme Inc. Ltd"},
            explicitly_updated=frozenset({"manufacturer"}),
        )
        assert cleaned == "Relay. Part/model number: P-1."
        assert "Ltd" not in cleaned


def test_nonfinancial_technical_value_fields_are_aggregated():
    result = aggregate_description(
        "Assorted electrical components.",
        custom_fields={
            "Resistance Value": "100 ohm",
            "Capacitance Value": "10uF",
            "Total Capacity": "10A",
            "Reference Price": "£3.00",
        },
    )
    assert "Resistance Value: 100 ohm." in result
    assert "Capacitance Value: 10uF." in result
    assert "Total Capacity: 10A." in result
    assert "£3.00" not in result


def test_slash_suffix_is_not_a_complete_model_match():
    result = aggregate_description("Alternative model ABC-123/4.", model_number="ABC-123")
    assert "Part/model number: ABC-123." in result


def test_blank_manufacturer_label_does_not_consume_user_notes():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    original = "Relay. Manufacturer:\n\nKeep these safety notes."
    cleaned = remove_superseded_generated_identifiers(
        original, manufacturer="NewCo", explicitly_updated=frozenset({"manufacturer"})
    )
    assert "Keep these safety notes." in cleaned
    assert cleaned.startswith("Relay.")


def test_financial_vat_token_does_not_exclude_activation_voltage():
    result = aggregate_description(
        "Sensor control board.",
        custom_fields={"Activation Voltage": "5V", "VAT Reference": "VAT-12"},
    )
    assert "Activation Voltage: 5V." in result
    assert "VAT-12" not in result


def test_ai_validation_defers_overflow_to_guarded_response_boundary():
    from fastapi import HTTPException

    from homebox_companion.tools.vision.models import get_items_adapter
    from server.api.tools.vision import aggregate_description_or_422

    raw = "A" * 992
    parsed = get_items_adapter(None).validate_python(
        [{"name": "Relay", "description": raw, "manufacturer": "ExampleCo", "modelNumber": "P-1"}]
    )[0]
    assert parsed.description == raw
    with pytest.raises(HTTPException) as error:
        aggregate_description_or_422(
            parsed.description, manufacturer=parsed.manufacturer, model_number=parsed.model_number
        )
    assert error.value.status_code == 422
    assert "1000 characters" in str(error.value.detail)


def test_superseded_identifiers_preserve_following_user_sentences():
    """A same-line safety note survives both correction and removal of the preceding field."""
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Relay. Manufacturer: Acme. Keep disconnected until installed."
    assert (
        remove_superseded_generated_identifiers(
            raw, manufacturer="Acme", explicitly_updated=frozenset({"manufacturer"})
        )
        == raw
    )
    for replacement in ("NewCo", None):
        cleaned = remove_superseded_generated_identifiers(
            raw,
            manufacturer=replacement,
            previous_identifiers={"manufacturer": "Acme"},
            explicitly_updated=frozenset({"manufacturer"}),
        )
        assert "Keep disconnected until installed." in cleaned
        assert "Manufacturer: Acme" not in cleaned
        assert "Relay." in cleaned


def test_dotted_manufacturer_followed_by_user_prose_is_preserved():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Relay. Manufacturer: Acme Inc. Ltd. Keep these safety notes."
    cleaned = remove_superseded_generated_identifiers(
        raw,
        manufacturer="NewCo",
        previous_identifiers={"manufacturer": "Acme Inc. Ltd"},
        explicitly_updated=frozenset({"manufacturer"}),
    )
    assert "Keep these safety notes." in cleaned
    assert "Acme Inc. Ltd" not in cleaned


def test_only_whole_word_technical_field_names_are_aggregated():
    result = aggregate_description(
        "Electronic component.",
        custom_fields={
            "Storage Preferences": "Personal settings",
            "Concurrent Users": "5",
            "Current Rating": "12A",
            "Supplier Part Number": "A-123",
        },
    )
    assert "Storage Preferences" not in result
    assert "Concurrent Users" not in result
    assert "Current Rating: 12A." in result
    assert "Supplier Part Number: A-123." in result


def test_initialled_dotted_manufacturer_names_are_not_split_into_prose():
    """Initials are part of the manufacturer when retaining, correcting, or removing its generated clause."""
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Relay. Manufacturer: A. O. Smith."
    assert (
        remove_superseded_generated_identifiers(
            raw,
            manufacturer="A. O. Smith",
            previous_identifiers={"manufacturer": "A. O. Smith"},
            explicitly_updated=frozenset({"manufacturer"}),
        )
        == raw
    )
    for replacement in ("NewCo", None):
        cleaned = remove_superseded_generated_identifiers(
            raw,
            manufacturer=replacement,
            previous_identifiers={"manufacturer": "A. O. Smith"},
            explicitly_updated=frozenset({"manufacturer"}),
        )
        assert cleaned == "Relay."


def test_dotted_manufacturer_names_followed_by_safety_prose_remain_intact():
    """An unchanged name and the following user sentence must both survive a save."""
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Relay. Manufacturer: A. O. Smith. Keep disconnected until installed."
    for replacement in ("A. O. Smith", "NewCo", None):
        cleaned = remove_superseded_generated_identifiers(
            raw,
            manufacturer=replacement,
            previous_identifiers={"manufacturer": "A. O. Smith"},
            explicitly_updated=frozenset({"manufacturer"}),
        )
        assert "Keep disconnected until installed." in cleaned
        if replacement == "A. O. Smith":
            assert cleaned == raw
        else:
            assert "A. O. Smith" not in cleaned


def test_one_initial_plus_surname_is_preserved_or_removed_whole():
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = "Relay. Manufacturer: A. Smith."
    assert (
        remove_superseded_generated_identifiers(
            raw,
            manufacturer="A. Smith",
            previous_identifiers={"manufacturer": "A. Smith"},
            explicitly_updated=frozenset({"manufacturer"}),
        )
        == raw
    )
    assert (
        remove_superseded_generated_identifiers(
            raw,
            manufacturer="NewCo",
            previous_identifiers={"manufacturer": "A. Smith"},
            explicitly_updated=frozenset({"manufacturer"}),
        )
        == "Relay."
    )


@pytest.mark.parametrize("name", ["W. L. Gore", "St. Jude", "Dr. Martens", "A. O. Smith"])
def test_dotted_brands_are_preserved_when_unchanged_with_or_without_following_prose(name):
    """Saving matching structured metadata must preserve the original description verbatim."""
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    for extra in ("", " Keep disconnected until installed."):
        raw = f"Relay. Manufacturer: {name}.{extra}"
        assert (
            remove_superseded_generated_identifiers(
                raw, manufacturer=name, explicitly_updated=frozenset({"manufacturer"})
            )
            == raw
        )


@pytest.mark.parametrize("name", ["W. L. Gore", "St. Jude", "Dr. Martens", "A. O. Smith"])
def test_correcting_dotted_brands_preserves_user_prose(name):
    from homebox_companion.tools.vision.description_policy import remove_superseded_generated_identifiers

    raw = f"Relay. Manufacturer: {name}. Keep disconnected until installed."
    cleaned = remove_superseded_generated_identifiers(
        raw,
        manufacturer="NewBrand",
        previous_identifiers={"manufacturer": name},
        explicitly_updated=frozenset({"manufacturer"}),
    )
    assert "Keep disconnected until installed." in cleaned
    assert name not in cleaned


def test_technical_fields_with_identical_numeric_values_are_all_in_description():
    result = aggregate_description("Controller.", custom_fields={"Voltage": "12", "Current": "12"})
    assert "Voltage: 12." in result
    assert "Current: 12." in result


def test_unrelated_quantity_does_not_suppress_a_custom_capacity():
    result = aggregate_description("Converter with 2 ports.", custom_fields={"Capacity": "2"})
    assert "Capacity: 2." in result


def test_shorter_field_label_does_not_match_longer_custom_field():
    result = aggregate_description("Controller. Activation Voltage: 5V.", custom_fields={"Voltage": "5V"})
    assert result == "Controller. Activation Voltage: 5V. Voltage: 5V."


def test_technical_custom_field_does_not_duplicate_its_exact_labelled_value():
    description = "Controller. Current: 12A."
    assert aggregate_description(description, custom_fields={"Current": "12A"}) == description


def test_custom_specifications_are_idempotent_after_unpunctuated_narrative():
    fields = {"Current": "12"}
    description = aggregate_description("Controller", custom_fields=fields)
    assert aggregate_description(description, custom_fields=fields) == description


@pytest.mark.parametrize("separator", [";", ".", "!", "?"])
def test_punctuated_custom_fields_remain_idempotent(separator):
    description = f"Controller. Voltage: 12V{separator} Current: 2A."
    assert aggregate_description(description, custom_fields={"Voltage": "12V", "Current": "2A"}) == description


def test_unrelated_numeric_quantity_does_not_suppress_a_model_number():
    assert aggregate_description("A switch with 24 ports.", model_number="24") == (
        "A switch with 24 ports. Part/model number: 24."
    )


@pytest.mark.parametrize("ending", ["", "\nKeep dry.", "\r\nKeep dry."])
def test_unpunctuated_labelled_specification_ends_at_the_line_boundary(ending):
    description = f"Controller. Voltage: 12V{ending}"
    assert aggregate_description(description, custom_fields={"Voltage": "12V"}) == description


@pytest.mark.parametrize("value", ["ABC-123", "A7", "24"])
def test_a_serial_in_prose_cannot_hide_a_model_with_the_same_value(value):
    serial_only = f"Device, serial {value}."
    assert aggregate_description(serial_only, serial_number=value, model_number=value) == (
        f"{serial_only} Part/model number: {value}."
    )
    both = f"Device, model {value}, serial {value}."
    assert aggregate_description(both, serial_number=value, model_number=value) == both


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_a_model_cue_on_another_line_cannot_claim_a_short_brand(newline):
    original = f"Spare part{newline}A7 relay."
    assert aggregate_description(original, manufacturer="A7", model_number="A7") == (
        f"{original} Part/model number: A7."
    )


def test_colon_bearing_identity_cues_are_read_only_before_authored_headings():
    text = "Device, model: A7, serial: B2. Safety: model: Z9 is recalled."
    assert aggregate_description(text, model_number="A7", serial_number="B2") == text
    assert aggregate_description(text, model_number="Z9") == f"{text} Part/model number: Z9."


@pytest.mark.parametrize("gap", ["\u00a0", "\u202f", "\u3000", "\t"])
def test_unicode_horizontal_spaces_keep_serial_numbers_distinct_from_models(gap):
    text = f"Device, serial{gap}number:{gap}ABC-123."
    assert aggregate_description(text, model_number="ABC-123", serial_number="ABC-123") == (
        f"{text} Part/model number: ABC-123."
    )
