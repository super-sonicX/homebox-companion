import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { detectedItems } from './fixtures/data';
import { selectLocation, uploadPhoto, analyzePhotos } from './helpers/scan';

const result = {
	id: 'signed-provider-token',
	thumbnail_url:
		'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+eL0kAAAAASUVORK5CYII=',
	title: 'Test catalogue image',
	source: 'example.org',
	source_url: 'https://example.org/product',
	license: '',
	attribution: '',
	rank: 1,
};

function mockLibrary(api: {
	on: (method: string, path: string, handler: () => ReturnType<typeof json>) => void;
}) {
	api.on('GET', '/api/library-images/config', () => json({ serpapi_configured: true }));
	api.on('GET', '/api/library-images/search', () =>
		json({ provider: 'serpapi', query: 'Storage box', results: [result] })
	);
}

test('Review lets a catalogue photo join the gallery without replacing originals', async ({
	page,
	api,
}) => {
	mockLibrary(api);
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Storage box'])));
	api.on('GET', '/api/library-images/download', () => ({
		status: 200,
		contentType: 'image/jpeg',
		body: 'mock image bytes',
	}));
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('tab', { name: 'Library Images' }).click();
	await expect(page.getByRole('heading', { name: 'Library Images' })).toBeVisible();
	const providers = page.getByRole('group', { name: 'Image search provider' });
	await expect(providers.getByRole('button')).toHaveCount(2);
	await expect(providers.getByRole('button', { name: 'Google Images Lite' })).toBeVisible();
	await expect(providers.getByRole('button', { name: 'eBay Search' })).toBeVisible();
	await expect(
		page.getByText('Choose an image provider above to search.', { exact: false })
	).toBeVisible();
	await page.getByRole('button', { name: 'Google Images Lite' }).click();
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	await page.getByRole('button', { name: 'Add to gallery' }).click();
	await expect(page.getByRole('tab', { name: 'Your Photos (2)' })).toBeVisible();
});

test('Review can set a selected catalogue image as the custom thumbnail', async ({ page, api }) => {
	mockLibrary(api);
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Storage box'])));
	api.on('GET', '/api/library-images/download', () => ({
		status: 200,
		contentType: 'image/jpeg',
		body: 'mock image bytes',
	}));
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('tab', { name: 'Library Images' }).click();
	await page.getByRole('button', { name: 'Google Images Lite' }).click();
	await page.getByRole('button', { name: 'Use as thumbnail' }).click();
	await expect(page.getByText('Custom', { exact: true })).toBeVisible();
});

test('Library tab adds a primary photo to an existing Homebox item on explicit action', async ({
	page,
	api,
}) => {
	mockLibrary(api);
	const payloads: unknown[] = [];
	api.on('GET', '/api/library-images/items', () =>
		json({
			items: [
				{
					id: 'item-1',
					name: 'Storage box',
					description: '',
					manufacturer: '',
					model_number: '',
					thumbnail_id: null,
				},
			],
			total: 1,
		})
	);
	api.on('GET', '/api/library-images/items/item-1', () =>
		json({
			id: 'item-1',
			name: 'Storage box',
			description: '',
			manufacturer: '',
			model_number: '',
			thumbnail_id: null,
			attachments: [],
		})
	);
	api.on('POST', '/api/library-images/items/item-1/attach', (request: any) => {
		payloads.push(request.postDataJSON());
		return json({
			id: 'item-1',
			name: 'Storage box',
			description: '',
			manufacturer: '',
			model_number: '',
			thumbnail_id: null,
			attachments: [],
		});
	});
	await page.goto('/library');
	await page.getByRole('button', { name: /Storage box/ }).click();
	await expect(page.getByText('Your item photographs (0)')).toBeVisible();
	await page.getByRole('button', { name: 'Find additional library images' }).click();
	await expect(
		page.getByText('Choose an image provider above to search.', { exact: false })
	).toBeVisible();
	await page.getByRole('button', { name: 'Google Images Lite' }).click();
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	await page.getByRole('button', { name: 'Use as thumbnail' }).click();
	expect(payloads).toEqual([{ image_id: 'signed-provider-token', primary: true }]);
	await expect(page.getByText(/1 catalogue photograph added this session/)).toBeVisible();
});

test('eBay image results are selected explicitly on the Review page', async ({ page, api }) => {
	const providers: string[] = [];
	api.on('GET', '/api/library-images/config', () => json({ serpapi_configured: true }));
	api.on('GET', '/api/library-images/search', (request) => {
		providers.push(new URL(request.url()).searchParams.get('provider') ?? '');
		return json({
			provider: providers.at(-1),
			query: 'Storage box',
			results: [result],
		});
	});
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Storage box'])));
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('tab', { name: 'Library Images' }).click();
	await expect(
		page.getByText('Choose an image provider above to search.', { exact: false })
	).toBeVisible();
	expect(providers).toEqual([]);
	await page.getByRole('button', { name: 'eBay Search' }).click();
	await expect(page.getByText('These are eBay sellers', { exact: false })).toBeVisible();
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	expect(providers).toEqual(['ebay']);
});

test('SerpApi key can be configured from Library without using an OpenAI key', async ({
	page,
	api,
}) => {
	const savedKeys: Array<{ key: string }> = [];
	api.on('GET', '/api/library-images/config', () => json({ serpapi_configured: false }));
	api.on('PUT', '/api/library-images/config', (request) => {
		savedKeys.push(request.postDataJSON() as { key: string });
		return json({ serpapi_configured: true });
	});
	api.on('GET', '/api/library-images/search', () =>
		json({ provider: 'serpapi', query: 'Storage box', results: [result] })
	);
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Storage box'])));
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('tab', { name: 'Library Images' }).click();
	await page.getByRole('button', { name: 'Google Images Lite' }).click();
	await expect(page.getByText('Connect your SerpApi key once', { exact: false })).toBeVisible();
	await page.getByPlaceholder('SerpApi API key').fill('mock-serpapi-secret');
	await page.getByRole('button', { name: 'Save key' }).click();
	await expect(page.getByText('Search key saved. Click Search to retrieve images.')).toBeVisible();
	await expect(page.getByText('Test catalogue image')).toHaveCount(0);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	expect(savedKeys).toEqual([{ key: 'mock-serpapi-secret' }]);
});

test('opening and switching existing items never triggers search until a provider is clicked', async ({
	page,
	api,
}) => {
	const queries: string[] = [];
	api.on('GET', '/api/library-images/config', () => json({ serpapi_configured: true }));
	api.on('GET', '/api/library-images/items', () =>
		json({
			items: [
				{
					id: 'item-1',
					name: 'Polymaker dryer',
					description: '',
					manufacturer: 'Polymaker',
					model_number: 'PolyDryer',
					thumbnail_id: null,
				},
				{
					id: 'item-2',
					name: 'ESP32 board',
					description: '',
					manufacturer: 'Espressif',
					model_number: '',
					thumbnail_id: null,
				},
			],
			total: 2,
		})
	);
	for (const [id, name] of [
		['item-1', 'Polymaker dryer'],
		['item-2', 'ESP32 board'],
	]) {
		api.on('GET', '/api/library-images/items/' + id, () =>
			json({
				id,
				name,
				description: '',
				manufacturer: '',
				model_number: '',
				thumbnail_id: null,
				attachments: [],
			})
		);
	}
	api.on('GET', '/api/library-images/search', (request) => {
		queries.push(new URL(request.url()).searchParams.get('provider') ?? '');
		return json({ provider: 'serpapi', query: 'Product', results: [result] });
	});

	await page.goto('/library');
	await page.getByRole('button', { name: /Polymaker dryer/ }).click();
	await expect(page.getByText('Your item photographs (0)')).toBeVisible();
	await page.getByRole('button', { name: 'Find additional library images' }).click();
	await expect(
		page.getByText('Choose an image provider above to search.', { exact: false })
	).toBeVisible();
	expect(queries).toEqual([]);

	await page.getByRole('button', { name: 'Back to item search' }).click();
	await page.getByRole('button', { name: /ESP32 board/ }).click();
	await expect(page.getByText('Your item photographs (0)')).toBeVisible();
	await page.getByRole('button', { name: 'Find additional library images' }).click();
	await expect(
		page.getByText('Choose an image provider above to search.', { exact: false })
	).toBeVisible();
	expect(queries).toEqual([]);

	await page.getByRole('button', { name: 'Google Images Lite' }).click();
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	expect(queries).toEqual(['serpapi']);

	await page.getByRole('button', { name: 'Google Images Lite' }).click();
	await expect.poll(() => queries.length).toBe(2);
	expect(queries).toEqual(['serpapi', 'serpapi']);
});

test('eBay listing photos are fetched only after clicking View listing photos', async ({
	page,
	api,
}) => {
	const queries: string[] = [];
	let detailCalls = 0;
	api.on('GET', '/api/library-images/config', () => json({ serpapi_configured: true }));
	api.on('GET', '/api/library-images/search', (request) => {
		queries.push(new URL(request.url()).searchParams.get('provider') ?? '');
		return json({
			provider: 'ebay',
			query: 'Storage box',
			results: [
				{
					...result,
					title: 'Polymaker dryer — eBay listing',
					source: 'eBay UK',
					source_url: 'https://www.ebay.co.uk/itm/388216346120',
					product_id: '388216346120',
				},
			],
		});
	});
	api.on('GET', '/api/library-images/ebay-photos', (request) => {
		detailCalls++;
		expect(new URL(request.url()).searchParams.get('product_id')).toBe('388216346120');
		return json({
			product_id: '388216346120',
			title: 'Polymaker dryer — eBay listing',
			results: [
				{ ...result, id: 'signed-gallery-photo-1', title: 'Photo 1', product_id: '388216346120' },
				{ ...result, id: 'signed-gallery-photo-2', title: 'Photo 2', product_id: '388216346120' },
				{ ...result, id: 'signed-gallery-photo-3', title: 'Photo 3', product_id: '388216346120' },
			],
		});
	});
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Storage box'])));
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('tab', { name: 'Library Images' }).click();
	expect(queries).toEqual([]);
	expect(detailCalls).toBe(0);
	await page.getByRole('button', { name: 'eBay Search' }).click();
	await expect(page.getByText('Polymaker dryer — eBay listing')).toBeVisible();
	expect(queries).toEqual(['ebay']);
	expect(detailCalls).toBe(0);
	await page.getByRole('button', { name: 'View listing photos (extra API search)' }).click();
	await expect(page.getByText('Photo 3')).toBeVisible();
	expect(detailCalls).toBe(1);
	await page.getByRole('button', { name: 'Back to eBay listings' }).click();
	await expect(page.getByText('Polymaker dryer — eBay listing')).toBeVisible();
	expect(detailCalls).toBe(1);
});
