"""Keep known Homebox creations visible when later operations fail."""

from unittest.mock import AsyncMock

import httpx
import pytest

from homebox_companion import HomeboxAuthError, HomeboxClient
from homebox_companion.core.config import Settings
from server.api import items as items_api
from server.app import create_app
from server.dependencies import get_gateway

pytestmark = pytest.mark.unit


@pytest.fixture
def gateway(monkeypatch):
    # Gateway methods are dynamic delegates to this client's API surface.
    gateway = AsyncMock(spec=HomeboxClient)
    item = {"id": "created-id", "name": "Lamp", "parent": {"id": "location"}, "tags": [], "quantity": 1}
    gateway.create_item.return_value = item
    gateway.get_item.return_value = item
    gateway.update_item.return_value = item
    gateway.ensure_asset_ids.return_value = 0
    monkeypatch.setattr(items_api, "get_valid_tag_ids", AsyncMock(return_value=set()))
    return gateway


async def submit(gateway, items):
    app = create_app(Settings(disable_update_check=True))
    app.dependency_overrides[get_gateway] = lambda: gateway
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        return await client.post("/api/items", json={"items": items, "location_id": "location"})


@pytest.mark.asyncio
@pytest.mark.parametrize("extended", [False, True])
async def test_explicit_container_wins_over_location_with_or_without_enrichment(gateway, extended):
    item = {"name": "Lamp", "parent_id": "container", "location_id": "item-location"}
    if extended:
        item["manufacturer"] = "Example"
    response = await submit(gateway, [item])
    assert response.status_code == 200
    assert gateway.create_item.call_args.args[0].parent_id == "container"
    if extended:
        assert gateway.update_item.call_args.args[1]["parentId"] == "container"
    else:
        gateway.update_item.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["get_item", "update_item"])
async def test_post_create_auth_failure_returns_created_id_and_stops_batch(gateway, stage):
    getattr(gateway, stage).side_effect = HomeboxAuthError("Expired")
    response = await submit(
        gateway,
        [
            {"name": "Lamp", "purchase_price": 0},
            {"name": "Unattempted chair"},
            {"name": "Unattempted table"},
        ],
    )

    assert response.status_code == 207
    assert [item["id"] for item in response.json()["created"]] == ["created-id"]
    assert response.json()["errors"] == [
        "Authentication failed for 'Lamp'",
        "2 more item(s) not attempted due to auth failure",
    ]
    gateway.create_item.assert_awaited_once()
    gateway.delete_item.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_error", [RuntimeError("Unavailable"), HomeboxAuthError("Expired")])
async def test_failed_cleanup_returns_known_id_as_incomplete(gateway, cleanup_error):
    gateway.update_item.side_effect = RuntimeError("Update failed")
    gateway.delete_item.side_effect = cleanup_error

    response = await submit(gateway, [{"name": "Lamp", "manufacturer": "Example"}])

    assert response.status_code == 207
    assert response.json()["created"][0]["id"] == "created-id"
    assert response.json()["errors"]
    gateway.delete_item.assert_awaited_once_with("created-id")


@pytest.mark.asyncio
async def test_confirmed_cleanup_leaves_failure_safe_to_retry(gateway):
    gateway.update_item.side_effect = RuntimeError("Update failed")

    response = await submit(gateway, [{"name": "Lamp", "manufacturer": "Example"}])

    assert response.status_code == 207
    assert response.json()["created"] == []
    gateway.delete_item.assert_awaited_once_with("created-id")


@pytest.mark.asyncio
async def test_auth_failure_before_creation_does_not_claim_an_item_exists(gateway):
    gateway.create_item.side_effect = HomeboxAuthError("Expired")

    response = await submit(gateway, [{"name": "Lamp", "purchase_price": 0}])

    assert response.status_code == 207
    assert response.json()["created"] == []
    gateway.delete_item.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        {"quantity": 0},
        {"quantity": 1.5},
        {"quantity": ""},
        {"name": "   "},
        {"name": "x" * 256},
        {"purchase_price": -1},
    ],
)
async def test_invalid_batch_rejected_before_any_creation(gateway, invalid):
    response = await submit(gateway, [{"name": "Valid first"}, {"name": "Invalid second", **invalid}])
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:3] == ["body", "items", 1]
    gateway.create_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_trimmed_name_and_zero_price_are_accepted(gateway):
    response = await submit(gateway, [{"name": "  Lamp  ", "quantity": 1, "purchase_price": 0}])
    assert response.status_code == 200
    assert gateway.create_item.call_args.args[0].name == "Lamp"


@pytest.mark.asyncio
async def test_create_aggregates_edited_manufacturer_model_and_custom_part_number(gateway):
    """The final editor values must be in Description, not only separate fields."""
    response = await submit(
        gateway,
        [
            {
                "name": "Front Bumper Bracket Set Peugeot 308",
                "description": "Replacement front bumper mounting brackets for a Peugeot 308.",
                "manufacturer": "Peugeot",
                "model_number": "PG4301005",
                "custom_fields": {"Supplier Part Number": "ABC-123"},
            }
        ],
    )
    assert response.status_code == 200
    created = gateway.create_item.call_args.args[0]
    assert "Peugeot" in created.description
    assert "PG4301005" in created.description
    assert "ABC-123" in created.description
    assert "packaging" not in created.description
    assert gateway.update_item.await_args.args[1]["modelNumber"] == "PG4301005"
    assert gateway.update_item.await_args.args[1]["manufacturer"] == "Peugeot"


@pytest.mark.asyncio
async def test_create_does_not_duplicate_identifiers_already_in_description(gateway):
    response = await submit(
        gateway,
        [
            {
                "name": "Molex Connector",
                "description": "Molex connector, part 50-57-9503.",
                "manufacturer": "Molex",
                "model_number": "50-57-9503",
            }
        ],
    )
    assert response.status_code == 200
    created = gateway.create_item.call_args.args[0]
    assert created.description == "Molex connector, part 50-57-9503."


@pytest.mark.asyncio
async def test_create_removes_old_generated_identifiers_from_edited_fields(gateway):
    """Check the exact identity passed to Homebox after a user corrects the detection."""
    response = await submit(
        gateway,
        [
            {
                "name": "Peugeot brackets",
                "description": "Peugeot bumper brackets. Manufacturer: WrongCo. Part/model number: OLD-123.",
                "manufacturer": "RightCo",
                "previous_identifiers": {"manufacturer": "WrongCo", "model_number": "OLD-123"},
                "model_number": "NEW-456",
            }
        ],
    )
    assert response.status_code == 200
    created = gateway.create_item.call_args.args[0]
    assert "RightCo" in created.description and "NEW-456" in created.description
    assert "WrongCo" not in created.description and "OLD-123" not in created.description


@pytest.mark.asyncio
async def test_create_removes_old_generated_model_when_explicitly_cleared(gateway):
    response = await submit(
        gateway,
        [
            {
                "name": "Peugeot brackets",
                "description": "Peugeot bumper brackets. Part/model number: OLD-123.",
                "model_number": None,
                "previous_identifiers": {"model_number": "OLD-123"},
            }
        ],
    )
    assert response.status_code == 200
    created = gateway.create_item.call_args.args[0]
    assert created.description == "Peugeot bumper brackets."


@pytest.mark.asyncio
async def test_create_dotted_manufacturer_does_not_leave_orphaned_suffix(gateway):
    """Exercise the create endpoint so partial manufacturer names cannot reach Homebox."""
    response = await submit(
        gateway,
        [
            {
                "name": "Relay",
                "description": "Relay. Manufacturer: Acme Inc. Ltd. Part/model number: P-1.",
                "previous_identifiers": {"manufacturer": "Acme Inc. Ltd"},
                "manufacturer": "NewCo",
                "model_number": "P-1",
            }
        ],
    )
    assert response.status_code == 200
    created = gateway.create_item.call_args.args[0]
    assert "Acme" not in created.description and "Ltd" not in created.description
    assert "NewCo" in created.description and "Part/model number: P-1." in created.description


@pytest.mark.asyncio
@pytest.mark.parametrize("manufacturer", ["Acme", "A. Smith", "A. O. Smith", "St. Jude", "Dr. Martens"])
@pytest.mark.parametrize("submitted", ["unchanged", "corrected", "cleared"])
async def test_create_never_drops_user_safety_notes_after_generated_metadata(gateway, manufacturer, submitted):
    """Verify the entire saved text, including the user note and the absence of any orphaned surname."""
    submitted_manufacturer = manufacturer if submitted == "unchanged" else "NewCo" if submitted == "corrected" else None
    response = await submit(
        gateway,
        [
            {
                "name": "Relay",
                "description": f"Relay. Manufacturer: {manufacturer}. Keep disconnected until installed.",
                "manufacturer": submitted_manufacturer,
                **({"previous_identifiers": {"manufacturer": manufacturer}} if submitted != "unchanged" else {}),
            }
        ],
    )
    assert response.status_code == 200
    created = gateway.create_item.call_args.args[0]
    assert "Keep disconnected until installed." in created.description
    if submitted == "corrected":
        assert created.description == "Relay. Keep disconnected until installed. Manufacturer: NewCo."
    elif submitted == "cleared":
        assert created.description == "Relay. Keep disconnected until installed."
    else:
        assert created.description == f"Relay. Manufacturer: {manufacturer}. Keep disconnected until installed."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "label"), [("model_number", "Part/model number"), ("serial_number", "Serial number")]
)
async def test_single_character_identifier_correction_preserves_short_warnings(gateway, field, label):
    response = await submit(
        gateway,
        [
            {
                "name": "Relay",
                "description": f"Relay. {label}: X. Flammable. Keep away from heat.",
                field: "Y",
                "previous_identifiers": {field: "X"},
            }
        ],
    )
    assert response.status_code == 200
    assert gateway.create_item.call_args.args[0].description == f"Relay. Flammable. Keep away from heat. {label}: Y."


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Compatible Manufacturer", "Previous Part/model number", "Original Serial number"])
async def test_create_preserves_longer_authored_headings(gateway, label):
    field = {
        "Compatible Manufacturer": "manufacturer",
        "Previous Part/model number": "model_number",
        "Original Serial number": "serial_number",
    }[label]
    own = {"manufacturer": "Manufacturer", "model_number": "Part/model number", "serial_number": "Serial number"}[field]
    original = f"Adapter. {label}: Acme."
    response = await submit(gateway, [{"name": "Adapter", "description": original, field: "NewCo"}])
    assert response.status_code == 200
    assert gateway.create_item.call_args.args[0].description == f"{original} {own}: NewCo."


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [None, "X", "X. Flammable"])
async def test_ambiguous_company_and_warning_require_matching_source(gateway, previous):
    """The same text can encode either a brand or a warning. Never infer permission to delete the warning."""
    description = "Relay. Manufacturer: X. Flammable. Keep away from heat."
    item = {"name": "Relay", "description": description, "manufacturer": "NewCo"}
    if previous:
        item["previous_identifiers"] = {"manufacturer": previous}
    response = await submit(gateway, [item])
    if previous is None:
        assert response.status_code == 207
        assert "Cannot safely separate" in response.json()["errors"][0]
        gateway.create_item.assert_not_awaited()
    else:
        assert response.status_code == 200
        note = "Flammable. " if previous == "X" else ""
        assert (
            gateway.create_item.call_args.args[0].description
            == f"Relay. {note}Keep away from heat. Manufacturer: NewCo."
        )


@pytest.mark.asyncio
async def test_create_keeps_an_unpunctuated_manufacturer_at_the_description_limit(gateway):
    tail = ".\nManufacturer: Acme\nKeep dry."
    description = "x" * (1000 - len(tail)) + tail
    response = await submit(gateway, [{"name": "Relay", "description": description, "manufacturer": "Acme"}])
    assert response.status_code == 200
    assert gateway.create_item.call_args.args[0].description == description


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Acme", "St. Jude", "Acme Inc."])
@pytest.mark.parametrize("state", ["unchanged", "corrected", "cleared"])
async def test_authored_recall_warning_in_a_manufacturer_clause_is_never_removed(gateway, name, state):
    description = f"Relay. Manufacturer: {name} (recalled; do not energize)."
    desired = {"unchanged": name, "corrected": "NewCo", "cleared": None}[state]
    item = {"name": "Relay", "description": description, "manufacturer": desired}
    expected = description
    if state != "unchanged":
        item["previous_identifiers"] = {"manufacturer": name}
        expected = description.replace("Manufacturer:", "Previous manufacturer:")
        if desired:
            expected += " Manufacturer: NewCo."
    response = await submit(gateway, [item])
    assert response.status_code == 200
    assert gateway.create_item.call_args.args[0].description == expected


@pytest.mark.asyncio
async def test_unverified_labelled_content_is_not_deleted_or_written(gateway):
    response = await submit(
        gateway, [{"name": "Relay", "description": "Relay. Serial number: Check before use.", "serial_number": None}]
    )
    assert "Cannot safely separate" in response.json()["errors"][0]
    gateway.create_item.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("submitted", ["Acme Inc.", "NewCo Ltd.", None])
async def test_single_terminal_period_in_company_name_precedes_other_metadata(gateway, submitted):
    description = "Relay. Manufacturer: Acme Inc. Part/model number: P-1. Keep dry."
    item = {"name": "Relay", "description": description, "manufacturer": submitted, "model_number": "P-1"}
    if submitted != "Acme Inc.":
        item["previous_identifiers"] = {"manufacturer": "Acme Inc."}
    response = await submit(gateway, [item])
    assert response.status_code == 200
    expected = "Relay. Part/model number: P-1. Keep dry."
    if submitted == "Acme Inc.":
        expected = description
    elif submitted:
        expected += " Manufacturer: NewCo Ltd."
    assert gateway.create_item.call_args.args[0].description == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("gap", [" ", "\t"])
async def test_create_recognizes_spacing_before_a_label_colon(gateway, gap):
    description = f"Controller. Manufacturer{gap}: Acme. Voltage{gap}: 24V. Keep dry."
    item = {
        "name": "Controller",
        "description": description,
        "manufacturer": "NewCo",
        "previous_identifiers": {"manufacturer": "Acme"},
        "custom_fields": {"Voltage": "24V"},
    }
    response = await submit(gateway, [item])
    assert response.status_code == 200
    assert (
        gateway.create_item.call_args.args[0].description
        == f"Controller. Voltage{gap}: 24V. Keep dry. Manufacturer: NewCo."
    )
