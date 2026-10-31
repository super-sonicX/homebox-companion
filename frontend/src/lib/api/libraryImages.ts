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
	product_id?: string | null;
}

export interface LibraryItemSummary {
	id: string;
	name: string;
	description: string;
	manufacturer: string;
	model_number: string;
	thumbnail_id: string | null;
}

export interface LibraryPhoto {
	id: string;
	type: string;
	title: string;
	mime_type: string;
	primary: boolean;
}

export interface LibraryItemDetail extends LibraryItemSummary {
	quantity: number;
	serial_number: string;
	notes: string;
	asset_id: string;
	purchase_from: string;
	purchase_price: number | null;
	purchase_date: string;
	warranty_expires: string;
	warranty_details: string;
	updated_at: string;
	location: string;
	parent: string;
	tags: string[];
	attachments: LibraryPhoto[];
	gallery_order: string[];
	gallery_order_scope: 'companion';
}

export interface LibraryItemEdits {
	name: string;
	description: string;
	quantity: number;
	manufacturer: string;
	model_number: string;
	serial_number: string;
	notes: string;
	purchase_from: string;
	purchase_price: number | null;
	expected_updated_at?: string;
}

export const libraryImages = {
	config: () => request<{ serpapi_configured: boolean }>('/library-images/config'),
	setProviderKey: (key: string) =>
		request<{ serpapi_configured: boolean }>('/library-images/config', {
			method: 'PUT',
			body: JSON.stringify({ key }),
		}),
	search: (query: string, provider: 'serpapi' | 'ebay') =>
		request<{ results: LibraryImageResult[]; provider: string; query: string }>(
			'/library-images/search?q=' + encodeURIComponent(query) + '&provider=' + provider
		),
	ebayPhotos: (productId: string) =>
		request<{ product_id: string; title: string; results: LibraryImageResult[] }>(
			'/library-images/ebay-photos?product_id=' + encodeURIComponent(productId),
			{ timeout: 35_000 }
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
	items: (q: string, page = 1, pageSize = 40, signal?: AbortSignal) =>
		request<{
			items: LibraryItemSummary[];
			total: number;
			page: number;
			has_more: boolean;
		}>(
			'/library-images/items?q=' +
				encodeURIComponent(q) +
				'&page=' +
				page +
				'&page_size=' +
				pageSize,
			{ signal }
		),
	thumbnail: (itemId: string, attachmentId: string, signal?: AbortSignal) =>
		requestBlobUrl(
			'/library-images/items/' +
				encodeURIComponent(itemId) +
				'/thumbnail?attachment_id=' +
				encodeURIComponent(attachmentId),
			{ signal, timeout: 30_000 }
		),
	item: (id: string) =>
		request<LibraryItemDetail>('/library-images/items/' + encodeURIComponent(id)),
	editDetails: (id: string, values: LibraryItemEdits) =>
		request<LibraryItemDetail>('/library-images/items/' + encodeURIComponent(id) + '/details', {
			method: 'PUT',
			body: JSON.stringify(values),
		}),
	setPrimary: (id: string, photoId: string) =>
		request<LibraryItemDetail>(
			'/library-images/items/' +
				encodeURIComponent(id) +
				'/photos/' +
				encodeURIComponent(photoId) +
				'/primary',
			{ method: 'PUT' }
		),
	deletePhoto: (id: string, photoId: string) =>
		request<LibraryItemDetail>(
			'/library-images/items/' + encodeURIComponent(id) + '/photos/' + encodeURIComponent(photoId),
			{ method: 'DELETE' }
		),
	reorderPhotos: (id: string, orderedIds: string[]) =>
		request<LibraryItemDetail>(
			'/library-images/items/' + encodeURIComponent(id) + '/photos/order',
			{
				method: 'PUT',
				body: JSON.stringify({ ordered_ids: orderedIds }),
			}
		),
	attach: (id: string, imageId: string, primary: boolean) =>
		request<LibraryItemDetail>('/library-images/items/' + encodeURIComponent(id) + '/attach', {
			method: 'POST',
			body: JSON.stringify({ image_id: imageId, primary }),
			timeout: 40_000,
		}),
};
