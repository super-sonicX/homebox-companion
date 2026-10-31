"""Regression coverage for safe existing-Homebox-item editing and Companion photo order."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from homebox_companion import HomeboxClient, HomeboxGateway
from homebox_companion.core import library_gallery_order
from homebox_companion.homebox.auth import HomeboxAccess, HomeboxAuthKind
from server.api.library_images import (
    ItemDetailsUpdate,
    PhotoOrderUpdate,
    edit_existing_item,
    existing_item_detail,
    remove_existing_photo,
    set_existing_photo_primary,
    update_photo_order,
)


def inventory_fixture() -> dict:
    return {
        "id": "item-1",
        "name": "Polymaker filament box",
        "description": "Storage box",
        "quantity": 2,
        "manufacturer": "Polymaker",
        "modelNumber": "PolyDryer",
        "serialNumber": "SN-123",
        "notes": "Keep dry",
        "purchaseFrom": "Supplier",
        "purchasePrice": 23.50,
        "updatedAt": "2026-10-27T08:30:00Z",
        "assetId": "042",
        "parent": {"id": "container-xyz", "name": "3D Printing"},
        "locationId": None,
        "entityType": {"id": "type-1", "isLocation": False},
        "fields": [{"id": "custom-1", "type": "text", "name": "Colour", "textValue": "Blue"}],
        "tags": [{"id": "tag-1", "name": "Filament"}],
        "attachments": [
            {"id": "p1", "type": "photo", "mimeType": "image/jpeg", "title": "Camera photo", "primary": True},
            {"id": "p2", "type": "photo", "mimeType": "image/jpeg", "title": "Catalogue photo", "primary": False},
            {"id": "manual", "type": "document", "mimeType": "application/pdf", "title": "Manual"},
        ],
        "thumbnailId": "p1",
    }


@dataclass
class FakeGateway:
    record: dict
    group_id: str = "group-1"

    def __post_init__(self):
        self.access = HomeboxAccess(SecretStr("test-secret"), HomeboxAuthKind.API_KEY, "test-account", self.group_id)
        self.edits: list[dict] = []
        self.primary_updates: list[tuple] = []
        self.deleted: list[tuple] = []

    async def get_item(self, item_id):
        assert item_id == self.record["id"]
        return deepcopy(self.record)

    async def update_item(self, item_id, body):
        assert item_id == self.record["id"]
        self.edits.append(deepcopy(body))
        for field in (
            "name",
            "description",
            "quantity",
            "manufacturer",
            "modelNumber",
            "serialNumber",
            "notes",
            "purchaseFrom",
            "purchasePrice",
        ):
            if field in body:
                self.record[field] = body[field]
        self.record["updatedAt"] = "2026-10-27T11:30:00Z"
        return deepcopy(self.record)

    async def update_attachment(self, item_id, attachment_id, body):
        assert item_id == self.record["id"]
        self.primary_updates.append((attachment_id, deepcopy(body)))
        for photo in self.record["attachments"]:
            if photo["type"] == "photo":
                photo["primary"] = photo["id"] == attachment_id
        self.record["thumbnailId"] = attachment_id
        return deepcopy(self.record)

    async def delete_attachment(self, item_id, attachment_id):
        assert item_id == self.record["id"]
        self.deleted.append((item_id, attachment_id))
        self.record["attachments"] = [entry for entry in self.record["attachments"] if entry["id"] != attachment_id]
        if self.record["thumbnailId"] == attachment_id:
            self.record["thumbnailId"] = None


@pytest.fixture
def gallery_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(library_gallery_order, "_ORDER_DIR", tmp_path / "gallery-orders")
    return tmp_path


@pytest.mark.asyncio
async def test_get_item_exposes_complete_metadata_and_existing_photo_gallery(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    detail = await existing_item_detail("item-1", cast(HomeboxGateway, gateway))
    assert detail["name"] == "Polymaker filament box"
    assert detail["quantity"] == 2
    assert detail["serial_number"] == "SN-123"
    assert detail["model_number"] == "PolyDryer"
    assert detail["notes"] == "Keep dry"
    assert detail["asset_id"] == "042"
    assert detail["tags"] == ["Filament"]
    assert len(detail["attachments"]) == 2
    assert detail["gallery_order"] == ["p1", "p2"]
    assert detail["gallery_order_scope"] == "companion"


@pytest.mark.asyncio
async def test_updating_common_fields_preserves_tags_parent_and_custom_fields(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    changes = ItemDetailsUpdate(
        name="Dryer and spool box",
        description="Dryer on top shelf",
        quantity=4,
        manufacturer="Polymaker",
        model_number="PolyDryer V2",
        serial_number="SN-456",
        purchase_from="Local store",
        purchase_price=49.99,
        notes="Updated in Companion",
        expected_updated_at="2026-10-27T08:30:00Z",
    )
    result = await edit_existing_item("item-1", changes, cast(HomeboxGateway, gateway))
    assert result["name"] == "Dryer and spool box"
    assert result["quantity"] == 4
    assert result["serial_number"] == "SN-456"
    assert result["purchase_price"] == 49.99
    assert gateway.edits[0]["tagIds"] == ["tag-1"]
    assert gateway.edits[0]["fields"][0]["name"] == "Colour"
    assert gateway.edits[0]["parentId"] == "container-xyz"
    assert gateway.edits[0]["name"] == "Dryer and spool box"
    assert len(result["attachments"]) == 2


@pytest.mark.asyncio
async def test_fractional_quantity_is_preserved_for_homebox_027(gallery_path):
    """Homebox 0.27+ explicitly stores quantity as float64; never silently round it."""
    gateway = FakeGateway(inventory_fixture())
    result = await edit_existing_item(
        "item-1", ItemDetailsUpdate(quantity=1.5), cast(HomeboxGateway, gateway)
    )
    assert gateway.edits[0]["quantity"] == 1.5
    assert result["quantity"] == 1.5


@pytest.mark.asyncio
async def test_stale_edit_is_blocked_before_homebox_put(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    with pytest.raises(HTTPException) as error:
        await edit_existing_item(
            "item-1",
            ItemDetailsUpdate(name="Stale", expected_updated_at="2026-01-01T00:00:00Z"),
            cast(HomeboxGateway, gateway),
        )
    assert error.value.status_code == 409
    assert gateway.edits == []


@pytest.mark.asyncio
async def test_empty_name_is_rejected_before_homebox_put(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    with pytest.raises(HTTPException) as error:
        await edit_existing_item("item-1", ItemDetailsUpdate(name=" "), cast(HomeboxGateway, gateway))
    assert error.value.status_code == 422
    assert gateway.edits == []


@pytest.mark.asyncio
async def test_setting_existing_primary_keeps_other_attachments_and_caption(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    updated = await set_existing_photo_primary("item-1", "p2", cast(HomeboxGateway, gateway))
    assert updated["thumbnail_id"] == "p2"
    assert len(updated["attachments"]) == 2
    assert gateway.primary_updates == [("p2", {"primary": True, "type": "photo", "title": "Catalogue photo"})]
    assert next(x for x in updated["attachments"] if x["id"] == "p2")["primary"] is True


@pytest.mark.asyncio
async def test_photo_delete_is_exact_and_never_deletes_document_or_item(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    with pytest.raises(HTTPException) as error:
        await remove_existing_photo("item-1", "manual", cast(HomeboxGateway, gateway))
    assert error.value.status_code == 404
    assert gateway.deleted == []

    updated = await remove_existing_photo("item-1", "p2", cast(HomeboxGateway, gateway))
    assert gateway.deleted == [("item-1", "p2")]
    assert [x["id"] for x in updated["attachments"]] == ["p1"]
    assert any(x["id"] == "manual" for x in gateway.record["attachments"])
    assert updated["thumbnail_id"] == "p1"


@pytest.mark.asyncio
async def test_reordering_is_persistent_group_scoped_and_not_a_homebox_write(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    data = await update_photo_order("item-1", PhotoOrderUpdate(ordered_ids=["p2", "p1"]), cast(HomeboxGateway, gateway))
    assert data["gallery_order"] == ["p2", "p1"]
    assert gateway.edits == []
    again = await existing_item_detail("item-1", cast(HomeboxGateway, gateway))
    assert again["gallery_order"] == ["p2", "p1"]
    different_group = FakeGateway(inventory_fixture(), group_id="group-2")
    other = await existing_item_detail("item-1", cast(HomeboxGateway, different_group))
    assert other["gallery_order"] == ["p1", "p2"]
    stored_files = list((gallery_path / "gallery-orders").glob("*.json"))
    assert len(stored_files) == 1
    assert stored_files[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_reorder_rejects_stale_or_duplicate_ids(gallery_path):
    gateway = FakeGateway(inventory_fixture())
    for order in [["p1", "p1"], ["p1"], ["p1", "p2", "rogue"]]:
        with pytest.raises(HTTPException) as error:
            await update_photo_order("item-1", PhotoOrderUpdate(ordered_ids=order), cast(HomeboxGateway, gateway))
        assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_attachment_update_and_delete_use_exact_homebox_paths_and_method():
    calls: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = None
        if request.method == "PUT":
            import json

            body = json.loads(request.content)
        calls.append((request.method, request.url.path, body))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"id": "item-1"})

    async with HomeboxClient(base_url="https://homebox.example/v1", transport=httpx.MockTransport(handler)) as client:
        outcome = await client.update_attachment(
            "test-bearer",
            "item-1",
            "photo-2",
            {"primary": True, "type": "photo", "title": "Keep caption"},
        )
        assert outcome == {"id": "item-1"}
        await client.delete_attachment("test-bearer", "item-1", "photo-1")
    assert calls == [
        ("PUT", "/v1/entities/item-1/attachments/photo-2", {"primary": True, "type": "photo", "title": "Keep caption"}),
        ("DELETE", "/v1/entities/item-1/attachments/photo-1", None),
    ]
