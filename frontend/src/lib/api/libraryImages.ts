/** Search catalogue photos and attach explicitly selected results. */
import { request, requestBlobUrl } from './client';

export interface LibraryImageResult {
	id: string;
	thumbnail_url: string;
	title: string;
	source: string;
	source_url: string;
	license: string;
	attribution: string;
	rank: number;
}

export interface LibraryItemSummary {
	id: string;
	name: string;
	description: string;
	manufacturer: string;
	model_number: string;
	thumbnail_id: string | null;
}

export interface LibraryItemDetail extends LibraryItemSummary {
	attachments: Array<{ id: string; type: string; primary: boolean }>;
}

export const libraryImages = {
	config: () => request<{ google_configured: boolean }>('/library-images/config'),
	setGoogleKey: (key: string) =>
		request<{ google_configured: boolean }>('/library-images/config', {
			method: 'PUT',
			body: JSON.stringify({ key }),
		}),
	search: (query: string, provider: 'google' | 'openverse') =>
		request<{ results: LibraryImageResult[]; provider: string; query: string }>(
			'/library-images/search?q=' + encodeURIComponent(query) + '&provider=' + provider
		),
	async download(id: string): Promise<File> {
		const image = await requestBlobUrl(
			'/library-images/download?image_id=' + encodeURIComponent(id),
			{
				timeout: 35_000,
			}
		);
		try {
			const blob = await (await fetch(image.url)).blob();
			return new File([blob], 'catalogue-photo.jpg', { type: 'image/jpeg' });
		} finally {
			image.revoke();
		}
	},
	items: (q: string) =>
		request<{ items: LibraryItemSummary[]; total: number }>(
			'/library-images/items?q=' + encodeURIComponent(q)
		),
	item: (id: string) =>
		request<LibraryItemDetail>('/library-images/items/' + encodeURIComponent(id)),
	attach: (id: string, imageId: string, primary: boolean) =>
		request<LibraryItemDetail>('/library-images/items/' + encodeURIComponent(id) + '/attach', {
			method: 'POST',
			body: JSON.stringify({ image_id: imageId, primary }),
			timeout: 40_000,
		}),
};
