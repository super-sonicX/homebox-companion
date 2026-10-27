import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';

interface TestItem {
	id: string;
	name: string;
	description: string;
	manufacturer: string;
	model_number: string;
	thumbnail_id: string | null;
}

const item = (id: number, hasPhoto = false): TestItem => ({
	id: 'item-' + id,
	name: 'Inventory item ' + id,
	description: 'Stored on shelf ' + id,
	manufacturer: '',
	model_number: 'Model ' + id,
	thumbnail_id: hasPhoto ? 'primary-' + id : null,
});

function inventoryApi(
	api: {
		on: (method: string, path: string, handler: (request: any) => ReturnType<typeof json>) => void;
	},
	count: number,
	hasPhoto = false
) {
	api.on('GET', '/api/library-images/items', (request) => {
		const url = new URL(request.url());
		const page = Number(url.searchParams.get('page') ?? 1);
		const pageSize = Number(url.searchParams.get('page_size') ?? 40);
		expect(pageSize).toBe(40);
		const first = (page - 1) * pageSize + 1;
		const last = Math.min(first + pageSize - 1, count);
		const items = Array.from({ length: Math.max(0, last - first + 1) }, (_, i) =>
			item(first + i, hasPhoto)
		);
		return json({ items, page, total: count, has_more: page * pageSize < count });
	});
}

test('Standard list defaults to 40px thumbnails and remembers tiles only on this browser', async ({
	page,
	api,
}) => {
	inventoryApi(api, 3);
	await page.goto('/library');
	const select = page.getByRole('combobox', { name: 'Library view' });
	await expect(select).toHaveValue('standard');
	await expect(page.locator('[data-library-view="standard"] [data-library-item]')).toHaveCount(3);
	await expect(page.locator('[data-library-thumbnail]')).toHaveCount(3);
	const thumbWidth = await page
		.locator('[data-library-thumbnail]')
		.first()
		.evaluate((element) => Math.round(element.getBoundingClientRect().width));
	expect(thumbWidth).toBe(40);
	const firstRowHeight = await page
		.locator('[data-library-item]')
		.first()
		.evaluate((element) => Math.round(element.getBoundingClientRect().height));
	expect(firstRowHeight).toBeLessThanOrEqual(70);
	expect(firstRowHeight).toBeGreaterThanOrEqual(40);

	await select.selectOption('medium');
	await expect(page.locator('[data-library-view="medium"] [data-library-item]')).toHaveCount(3);
	await expect(page.locator('[data-library-thumbnail]')).toHaveCount(3);
	expect(await page.evaluate(() => localStorage.getItem('hbc_library_view_v1'))).toBe('medium');

	await page.reload();
	await expect(page.getByRole('combobox', { name: 'Library view' })).toHaveValue('medium');
	await expect(page.locator('[data-library-view="medium"]')).toBeVisible();

	await page.getByRole('combobox', { name: 'Library view' }).selectOption('large');
	await expect(page.locator('[data-library-view="large"]')).toBeVisible();
	await page.getByRole('combobox', { name: 'Library view' }).selectOption('compact');
	await expect(page.locator('[data-library-view="compact"] [data-library-item]')).toHaveCount(3);
	await expect(page.locator('[data-library-thumbnail]')).toHaveCount(0);
	await expect(page.getByRole('combobox', { name: 'Library view' })).toHaveValue('compact');

	const paidSearchCalls = api.requests.filter((req) =>
		req.url().includes('/api/library-images/search')
	);
	expect(paidSearchCalls).toHaveLength(0);
});

test('Load more retrieves successive 40-item pages without duplicates or image search', async ({
	page,
	api,
}) => {
	inventoryApi(api, 85);
	await page.goto('/library');
	await expect(page.locator('[data-library-item]')).toHaveCount(40);
	await expect(page.getByText('Showing 40 items')).toBeVisible();

	await page.getByRole('button', { name: 'Load more items' }).click();
	await expect(page.locator('[data-library-item]')).toHaveCount(80);
	await page.getByRole('button', { name: 'Load more items' }).click();
	await expect(page.locator('[data-library-item]')).toHaveCount(85);
	await expect(page.getByRole('button', { name: 'Load more items' })).toHaveCount(0);
	expect(
		await page
			.locator('[data-library-item]')
			.evaluateAll(
				(elements) =>
					new Set(elements.map((element) => element.getAttribute('data-library-item'))).size
			)
	).toBe(85);

	const pages = api.requests
		.filter((req) => new URL(req.url()).pathname === '/api/library-images/items')
		.map((req) => Number(new URL(req.url()).searchParams.get('page')));
	expect(pages).toEqual([1, 2, 3]);
	expect(
		api.requests.filter((req) => req.url().includes('/api/library-images/search'))
	).toHaveLength(0);
});

test('thumbnails are lazy loaded with at most four simultaneous requests and no placeholders shifting layout', async ({
	page,
	api,
}) => {
	inventoryApi(api, 30, true);
	let active = 0;
	let maxActive = 0;
	const gate = api.gate();
	api.on('GET', /\/api\/library-images\/items\/item-\d+\/thumbnail/, async (request) => {
		const url = new URL(request.url());
		expect(url.searchParams.get('attachment_id')).toMatch(/^primary-\d+$/);
		active++;
		maxActive = Math.max(maxActive, active);
		await gate.promise;
		active--;
		return { status: 200, contentType: 'image/jpeg', body: 'mock-jpeg-pixels' };
	});
	try {
		await page.goto('/library');
		await expect(page.locator('[data-library-item]')).toHaveCount(30);
		await expect.poll(() => active).toBeGreaterThan(0);
		expect(maxActive).toBeLessThanOrEqual(4);
		// Any pending/visible preview retains its 40px square while loading.
		const width = await page
			.locator('[data-library-thumbnail]')
			.first()
			.evaluate((element) => Math.round(element.getBoundingClientRect().width));
		expect(width).toBe(40);
	} finally {
		gate.release();
	}
	await expect.poll(() => active).toBe(0);
	expect(maxActive).toBeLessThanOrEqual(4);
	expect(
		api.requests.filter((req) => req.url().includes('/api/library-images/search'))
	).toHaveLength(0);
});

test('returning after a primary-photo change requests the new preview and preserves layout', async ({
	page,
	api,
}) => {
	const target = item(1, true);
	const photoRequests: string[] = [];
	api.on('GET', '/api/library-images/items', () =>
		json({ items: [target], page: 1, total: 1, has_more: false })
	);
	api.on('GET', '/api/library-images/items/item-1/thumbnail', (request) => {
		photoRequests.push(new URL(request.url()).searchParams.get('attachment_id') ?? '');
		return { status: 200, contentType: 'image/jpeg', body: 'mock-jpeg-pixels' };
	});
	api.on('GET', '/api/library-images/items/item-1', () => json({ ...target, attachments: [] }));
	api.on('GET', '/api/items/item-1/attachments/primary-1', () => ({
		status: 200,
		contentType: 'image/jpeg',
		body: 'mock-jpeg-pixels',
	}));
	api.on('GET', '/api/items/item-1/attachments/updated-primary', () => ({
		status: 200,
		contentType: 'image/jpeg',
		body: 'mock-jpeg-pixels',
	}));
	api.on('GET', '/api/library-images/config', () => json({ serpapi_configured: true }));
	api.on('GET', '/api/library-images/search', () =>
		json({
			provider: 'serpapi',
			query: 'Inventory item 1',
			results: [
				{
					id: 'signed-photo',
					thumbnail_url: '',
					title: 'Catalogue photo',
					source: 'manufacturer',
					source_url: '',
					attribution: '',
					license: '',
					rank: 1,
				},
			],
		})
	);
	api.on('POST', '/api/library-images/items/item-1/attach', () =>
		json({ ...target, thumbnail_id: 'updated-primary', attachments: [] })
	);
	await page.goto('/library');
	await expect(page.locator('[data-library-item]')).toHaveCount(1);
	await expect.poll(() => photoRequests.length).toBeGreaterThan(0);
	await page.locator('[data-library-item="item-1"]').click();
	await page.getByRole('button', { name: 'Google Images Lite' }).click();
	await page.getByRole('button', { name: 'Use as thumbnail' }).click();
	await expect(page.getByText('1 photo imported this session')).toBeVisible();
	await page.getByRole('button', { name: 'Back to item search' }).click();
	await expect(page.locator('[data-library-item]')).toHaveCount(1);
	await expect.poll(() => photoRequests.includes('updated-primary')).toBe(true);
	await expect(page.getByRole('combobox', { name: 'Library view' })).toHaveValue('standard');
});

test('saved view is not forced onto an independent browser context', async ({
	page,
	api,
	browser,
}) => {
	inventoryApi(api, 1);
	await page.goto('/library');
	await page.getByRole('combobox', { name: 'Library view' }).selectOption('large');
	await expect(page.getByRole('combobox', { name: 'Library view' })).toHaveValue('large');

	// Separate browser contexts do not share localStorage. Mock its API normally.
	const context = await browser.newContext();
	try {
		const { installApi } = await import('./fixtures/api');
		const otherApi = await installApi(context);
		inventoryApi(otherApi, 1);
		const other = await context.newPage();
		await other.goto('/library');
		await expect(other.getByRole('combobox', { name: 'Library view' })).toHaveValue('standard');
	} finally {
		await context.close();
	}
});

test('medium tile view uses two columns on a narrow phone screen', async ({ page, api }) => {
	inventoryApi(api, 6);
	await page.setViewportSize({ width: 390, height: 740 });
	await page.goto('/library');
	await page.getByRole('combobox', { name: 'Library view' }).selectOption('medium');
	await expect(page.locator('[data-library-view="medium"] [data-library-item]')).toHaveCount(6);
	const columnCount = await page
		.locator('[data-library-view="medium"]')
		.evaluate(
			(element) => getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/).length
		);
	expect(columnCount).toBe(2);
	const firstImageSize = await page
		.locator('[data-library-thumbnail]')
		.first()
		.evaluate((element) => Math.round(element.getBoundingClientRect().height));
	expect(firstImageSize).toBe(112);
});
