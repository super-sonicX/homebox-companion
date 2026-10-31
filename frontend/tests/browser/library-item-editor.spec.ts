import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';

function detail() {
	return {
		id: 'item-1',
		name: 'Storage box',
		description: 'Storage box on shelf',
		quantity: 2,
		manufacturer: 'Polymaker',
		model_number: 'PolyDryer',
		serial_number: 'SN-001',
		notes: 'Keep dry',
		asset_id: '042',
		purchase_from: 'Local shop',
		purchase_price: 22.5,
		purchase_date: '2025-11-01',
		warranty_expires: '2027-11-01',
		warranty_details: 'Two years',
		updated_at: '2026-10-27T08:30:00Z',
		location: 'Attic',
		parent: '3D Printing',
		tags: ['Filament'],
		thumbnail_id: 'p1',
		gallery_order: ['p1', 'p2'],
		gallery_order_scope: 'companion',
		attachments: [
			{ id: 'p1', type: 'photo', title: 'Camera photo', mime_type: 'image/jpeg', primary: true },
			{
				id: 'p2',
				type: 'photo',
				title: 'Catalogue photo',
				mime_type: 'image/jpeg',
				primary: false,
			},
		],
	};
}

function setupWorkspace(api: {
	on: (
		method: string,
		path: string | RegExp,
		handler: (request: any) => ReturnType<typeof json> | Promise<ReturnType<typeof json>>
	) => void;
}) {
	let data = detail();
	api.on('GET', '/api/library-images/items', () =>
		json({
			page: 1,
			total: 1,
			has_more: false,
			items: [
				{
					id: 'item-1',
					name: data.name,
					description: data.description,
					model_number: data.model_number,
					manufacturer: data.manufacturer,
					thumbnail_id: data.thumbnail_id,
				},
			],
		})
	);
	api.on('GET', '/api/library-images/items/item-1', () => json(data));
	api.on('GET', '/api/library-images/items/item-1/thumbnail', () => ({
		status: 200,
		contentType: 'image/jpeg',
		body: 'mock-image-bytes',
	}));
	api.on('GET', /\/api\/items\/item-1\/attachments\/p[12]/, () => ({
		status: 200,
		contentType: 'image/jpeg',
		body: 'mock-original-bytes',
	}));
	api.on('GET', /\/api\/items\/item-1\/attachments\/uploaded/, () => ({
		status: 200,
		contentType: 'image/jpeg',
		body: 'mock-upload-bytes',
	}));
	return {
		get: () => data,
		set: (newData: ReturnType<typeof detail>) => {
			data = newData;
		},
	};
}

test('Library opens with all existing photos, while Details and Edit remain explicit', async ({
	page,
	api,
}) => {
	setupWorkspace(api);
	await page.goto('/library');
	await page.getByRole('button', { name: /Storage box/ }).click();
	await expect(page.locator('[data-library-gallery] [data-gallery-photo]')).toHaveCount(2);
	await expect(page.locator('[data-item-details]')).toHaveCount(0);
	await expect(page.locator('[data-item-edit]')).toHaveCount(0);
	await expect(page.getByText('Camera photo')).toBeVisible();
	await expect(page.getByText('Catalogue photo', { exact: true })).toBeVisible();
	await expect(page.locator('[data-gallery-photo="p1"]').getByText('Primary')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Find additional library images' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Google Images Lite' })).toHaveCount(0);
	expect(api.requests.filter((r) => r.url().includes('/api/library-images/search'))).toHaveLength(
		0
	);

	await page.getByRole('button', { name: 'Details', exact: true }).click();
	const details = page.locator('[data-item-details]');
	await expect(details).toBeVisible();
	await expect(details).toContainText('SN-001');
	await expect(details).toContainText('Attic');
	await expect(details).toContainText('Filament');
	await expect(details).toContainText('Two years');
});

test('Edit submits common fields without altering image attachments or making SerpApi calls', async ({
	page,
	api,
}) => {
	const state = setupWorkspace(api);
	const posted: unknown[] = [];
	api.on('PUT', '/api/library-images/items/item-1/details', (request) => {
		const body = request.postDataJSON();
		posted.push(body);
		const updated = {
			...state.get(),
			name: body.name,
			description: body.description,
			quantity: body.quantity,
			serial_number: body.serial_number,
			model_number: body.model_number,
			notes: body.notes,
			purchase_price: body.purchase_price,
			updated_at: '2026-10-27T14:00:00Z',
		};
		state.set(updated);
		return json(updated);
	});
	await page.goto('/library');
	await page.locator('[data-library-item="item-1"]').click();
	await page.getByRole('button', { name: 'Edit', exact: true }).click();
	await expect(page.locator('[data-item-edit]')).toBeVisible();

	await page.getByRole('textbox', { name: 'Item title' }).fill('Polymaker PolyDryer box');
	await page.getByRole('textbox', { name: 'Description' }).fill('Sorted filament storage');
	await page.getByRole('spinbutton', { name: 'Quantity' }).fill('4');
	await page.getByRole('textbox', { name: 'Model / product number' }).fill('PolyDryer V2');
	await page.getByRole('textbox', { name: 'Serial number' }).fill('SN-TEST-002');
	await page.getByRole('textbox', { name: 'Notes' }).fill('Updated by Companion');
	await page.getByRole('textbox', { name: 'Purchase price' }).fill('43.50');
	await page.locator('[data-save-item]').click();
	await expect(page.getByText('Polymaker PolyDryer box').first()).toBeVisible();
	await expect(page.locator('[data-item-edit]')).toHaveCount(0);
	await expect(page.locator('[data-item-details]')).toContainText('SN-TEST-002');
	await expect(page.locator('[data-library-gallery] [data-gallery-photo]')).toHaveCount(2);
	expect(posted).toMatchObject([
		{
			name: 'Polymaker PolyDryer box',
			quantity: 4,
			purchase_price: 43.5,
			model_number: 'PolyDryer V2',
			serial_number: 'SN-TEST-002',
			expected_updated_at: '2026-10-27T08:30:00Z',
		},
	]);
	expect(api.requests.filter((r) => r.url().includes('/api/library-images/search'))).toHaveLength(
		0
	);
});

test('Photo order is saved only by explicit controls, then an existing image can become primary', async ({
	page,
	api,
}) => {
	const state = setupWorkspace(api);
	const orderCalls: unknown[] = [];
	const primaryCalls: string[] = [];
	api.on('PUT', '/api/library-images/items/item-1/photos/order', (request) => {
		const body = request.postDataJSON();
		orderCalls.push(body);
		const updated = { ...state.get(), gallery_order: body.ordered_ids };
		state.set(updated);
		return json(updated);
	});
	api.on('PUT', '/api/library-images/items/item-1/photos/p2/primary', () => {
		primaryCalls.push('p2');
		const updated = {
			...state.get(),
			thumbnail_id: 'p2',
			attachments: state.get().attachments.map((photo) => ({
				...photo,
				primary: photo.id === 'p2',
			})),
		};
		state.set(updated);
		return json(updated);
	});
	await page.goto('/library');
	await page.locator('[data-library-item="item-1"]').click();
	await page.getByRole('button', { name: 'Move photo 2 earlier' }).click();
	await expect(page.locator('[data-gallery-photo]').first()).toHaveAttribute(
		'data-gallery-photo',
		'p2'
	);
	expect(orderCalls).toEqual([{ ordered_ids: ['p2', 'p1'] }]);
	await page.getByRole('button', { name: 'Make photo 1 primary' }).click();
	await expect(page.locator('[data-gallery-photo="p2"]').getByText('Primary')).toBeVisible();
	expect(primaryCalls).toEqual(['p2']);
	await page.getByRole('button', { name: 'Back to item search' }).click();
	await expect(page.locator('[data-library-item="item-1"]')).toBeVisible();
});

test('Deleting a camera photo asks for confirmation, then removes only that image', async ({
	page,
	api,
}) => {
	const state = setupWorkspace(api);
	const deletes: string[] = [];
	api.on('DELETE', '/api/library-images/items/item-1/photos/p1', () => {
		deletes.push('p1');
		const updated = {
			...state.get(),
			thumbnail_id: 'p2',
			gallery_order: ['p2'],
			attachments: state
				.get()
				.attachments.filter((photo) => photo.id !== 'p1')
				.map((photo) => ({
					...photo,
					primary: photo.id === 'p2',
				})),
		};
		state.set(updated);
		return json(updated);
	});
	await page.goto('/library');
	await page.locator('[data-library-item="item-1"]').click();
	page.once('dialog', (dialog) => dialog.dismiss());
	await page.getByRole('button', { name: 'Delete photo 1' }).click();
	expect(deletes).toEqual([]);
	await expect(page.locator('[data-gallery-photo]')).toHaveCount(2);

	page.once('dialog', (dialog) => dialog.accept());
	await page.getByRole('button', { name: 'Delete photo 1' }).click();
	await expect(page.locator('[data-gallery-photo]')).toHaveCount(1);
	expect(deletes).toEqual(['p1']);
	await expect(page.locator('[data-gallery-photo="p2"]')).toBeVisible();
});

test('Camera/uploads and catalogue searches remain optional; selected files attach without replacing existing photos', async ({
	page,
	api,
}) => {
	const state = setupWorkspace(api);
	api.on('GET', '/api/library-images/config', () => json({ serpapi_configured: true }));
	const uploadCalls: string[] = [];
	api.on('POST', '/api/items/item-1/attachments', (request) => {
		uploadCalls.push(request.headers()['content-type'] ?? '');
		state.set({
			...state.get(),
			attachments: [
				...state.get().attachments,
				{
					id: 'uploaded',
					title: 'New camera photo',
					type: 'photo',
					mime_type: 'image/png',
					primary: false,
				},
			],
			gallery_order: ['p1', 'p2', 'uploaded'],
		});
		return json({ id: 'uploaded' });
	});
	await page.goto('/library');
	await page.locator('[data-library-item="item-1"]').click();
	await page.getByLabel('Upload item photos').setInputFiles({
		name: 'garage-shelf.jpg',
		mimeType: 'image/jpeg',
		buffer: Buffer.alloc(1024, 42),
	});
	await expect(page.locator('[data-gallery-photo]')).toHaveCount(3);
	expect(uploadCalls).toHaveLength(1);
	expect(uploadCalls[0]).toContain('multipart/form-data');
	await expect(page.locator('[data-gallery-photo="p1"]')).toBeVisible();
	await expect(page.locator('[data-gallery-photo="uploaded"]')).toBeVisible();
	expect(api.requests.filter((r) => r.url().includes('/api/library-images/search'))).toHaveLength(
		0
	);
	await page.getByRole('button', { name: 'Find additional library images' }).click();
	const providers = page.getByRole('group', { name: 'Image search provider' });
	await expect(providers.getByRole('button')).toHaveCount(2);
});
