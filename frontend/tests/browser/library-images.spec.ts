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
	api.on('GET', '/api/library-images/config', () => json({ google_configured: true }));
	api.on('GET', '/api/library-images/search', () =>
		json({ provider: 'google', query: 'Storage box', results: [result] })
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
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	await page.getByRole('button', { name: 'Use as thumbnail' }).click();
	expect(payloads).toEqual([{ image_id: 'signed-provider-token', primary: true }]);
	await expect(page.getByText(/1 photo imported this session/)).toBeVisible();
});

test('eBay image results are selected explicitly on the Review page', async ({ page, api }) => {
	const providers: string[] = [];
	api.on('GET', '/api/library-images/config', () =>
		json({ google_configured: false, serpapi_configured: true })
	);
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
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	await page.getByRole('button', { name: 'eBay listings' }).click();
	await expect(page.getByText('Searching image results from eBay UK listing pages.')).toBeVisible();
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	expect(providers).toEqual(['serpapi', 'ebay']);
});

test('SerpApi key can be configured from Library without using an OpenAI key', async ({
	page,
	api,
}) => {
	const savedKeys: Array<{ provider: string; key: string }> = [];
	api.on('GET', '/api/library-images/config', () =>
		json({ google_configured: false, serpapi_configured: false })
	);
	api.on('PUT', '/api/library-images/config', (request) => {
		savedKeys.push(request.postDataJSON() as { provider: string; key: string });
		return json({ google_configured: false, serpapi_configured: true });
	});
	api.on('GET', '/api/library-images/search', () =>
		json({ provider: 'serpapi', query: 'Storage box', results: [result] })
	);
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Storage box'])));
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('tab', { name: 'Library Images' }).click();
	await expect(page.getByText('250 searches per month')).toBeVisible();
	await page.getByPlaceholder('SerpApi API key').fill('mock-serpapi-secret');
	await page.getByRole('button', { name: 'Save key' }).click();
	await expect(page.getByText('Test catalogue image')).toBeVisible();
	expect(savedKeys).toEqual([{ provider: 'serpapi', key: 'mock-serpapi-secret' }]);
});
