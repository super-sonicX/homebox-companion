<script lang="ts">
	import { onMount, onDestroy, untrack } from 'svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		Search,
		Images,
		LoaderCircle,
		CheckCircle2,
		ArrowLeft,
		ChevronRight,
		LayoutGrid,
	} from '@lucide/svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { collectionStore } from '$lib/stores/collection.svelte';
	import { getInitPromise } from '$lib/services/bootstrap';
	import { showToast } from '$lib/stores/ui.svelte';
	import { items, type BlobUrlResult } from '$lib/api/items';
	import {
		libraryImages,
		type LibraryItemDetail,
		type LibraryItemSummary,
		type LibraryImageResult,
	} from '$lib/api/libraryImages';
	import LibraryImagePicker from '$lib/components/LibraryImagePicker.svelte';
	import LibraryItemThumbnail from '$lib/components/LibraryItemThumbnail.svelte';

	type LibraryView = 'compact' | 'standard' | 'medium' | 'large';

	const VIEW_STORAGE_KEY = 'hbc_library_view_v1';
	const VIEWS: readonly LibraryView[] = ['compact', 'standard', 'medium', 'large'];
	const PAGE_SIZE = 40;
	const MAX_THUMB_CONCURRENCY = 4;
	const MAX_THUMB_CACHE = 150;

	let viewMode = $state<LibraryView>('standard');
	let ready = $state(false);
	let query = $state('');
	let inventory = $state<LibraryItemSummary[]>([]);
	let total = $state(0);
	let hasMore = $state(false);
	let isLoading = $state(false);
	let loadingMore = $state(false);
	let message = $state('');
	let selected = $state<LibraryItemDetail | null>(null);
	let loadingItem = $state(false);
	let savedCount = $state(0);
	let imageUrl = $state<string | null>(null);
	let revokeImage: (() => void) | null = null;
	let committedQuery = '';
	let currentPage = 0;
	let listGeneration = 0;
	let detailGeneration = 0;
	let detailImageGeneration = 0;
	let listController: AbortController | null = null;

	// Blob URLs stay cached while switching list/tile views. Individual visible
	// thumbnails are loaded at most four at a time, then revoked on search/group
	// changes, cache eviction or page teardown.
	const thumbnailResults = new SvelteMap<string, BlobUrlResult>();
	let thumbnailController = new AbortController();
	let thumbnailGeneration = 0;
	let thumbnailActive = 0;
	let thumbnailQueue: LibraryItemSummary[] = [];
	const queuedThumbs = new SvelteSet<string>();
	const loadingThumbs = new SvelteSet<string>();
	const failedThumbs = new SvelteSet<string>();

	function thumbKey(item: LibraryItemSummary): string {
		return item.id + ':' + (item.thumbnail_id ?? '');
	}

	function thumbnailUrl(item: LibraryItemSummary): string | null {
		return thumbnailResults.get(thumbKey(item))?.url ?? null;
	}

	function releaseThumbnails() {
		thumbnailGeneration++;
		thumbnailController.abort();
		thumbnailController = new AbortController();
		thumbnailQueue = [];
		queuedThumbs.clear();
		loadingThumbs.clear();
		failedThumbs.clear();
		thumbnailActive = 0;
		for (const result of thumbnailResults.values()) result.revoke();
		thumbnailResults.clear();
	}

	function requestThumbnail(item: LibraryItemSummary) {
		if (!item.thumbnail_id) return;
		const key = thumbKey(item);
		if (
			thumbnailResults.has(key) ||
			queuedThumbs.has(key) ||
			loadingThumbs.has(key) ||
			failedThumbs.has(key)
		)
			return;
		queuedThumbs.add(key);
		thumbnailQueue.push(item);
		drainThumbnailQueue();
	}

	function drainThumbnailQueue() {
		while (thumbnailActive < MAX_THUMB_CONCURRENCY && thumbnailQueue.length > 0) {
			const item = thumbnailQueue.shift()!;
			const key = thumbKey(item);
			queuedThumbs.delete(key);
			if (!item.thumbnail_id || thumbnailResults.has(key) || loadingThumbs.has(key)) continue;
			const generation = thumbnailGeneration;
			const signal = thumbnailController.signal;
			loadingThumbs.add(key);
			thumbnailActive++;
			void libraryImages
				.thumbnail(item.id, item.thumbnail_id, signal)
				.then((result) => {
					if (generation !== thumbnailGeneration || signal.aborted) {
						result.revoke();
						return;
					}
					// Limit browser memory when the user loads hundreds of items.
					while (thumbnailResults.size >= MAX_THUMB_CACHE) {
						const oldest = thumbnailResults.keys().next().value;
						if (!oldest) break;
						thumbnailResults.get(oldest)?.revoke();
						thumbnailResults.delete(oldest);
					}
					thumbnailResults.set(key, result);
				})
				.catch((error) => {
					if (
						generation === thumbnailGeneration &&
						!signal.aborted &&
						!(error instanceof Error && error.name === 'AbortError')
					) {
						failedThumbs.add(key);
					}
				})
				.finally(() => {
					if (generation !== thumbnailGeneration) return;
					loadingThumbs.delete(key);
					thumbnailActive--;
					drainThumbnailQueue();
				});
		}
	}

	function invalidateItemThumbnail(itemId: string) {
		for (const key of thumbnailResults.keys()) {
			if (!key.startsWith(itemId + ':')) continue;
			thumbnailResults.get(key)?.revoke();
			thumbnailResults.delete(key);
		}
		// A newly selected primary photo must be retryable even if the old one failed.
		for (const key of failedThumbs) if (key.startsWith(itemId + ':')) failedThumbs.delete(key);
	}

	function setViewMode(next: LibraryView) {
		viewMode = next;
		try {
			localStorage.setItem(VIEW_STORAGE_KEY, next);
		} catch {
			// Private browsing may disable storage. View selection still works.
		}
	}

	function clearDetailPreview() {
		detailImageGeneration++;
		revokeImage?.();
		revokeImage = null;
		imageUrl = null;
	}

	onMount(async () => {
		try {
			const stored = localStorage.getItem(VIEW_STORAGE_KEY);
			if (VIEWS.includes(stored as LibraryView)) viewMode = stored as LibraryView;
		} catch {
			// Use the default Standard list where localStorage is unavailable.
		}
		await getInitPromise();
		if (!authStore.isAuthenticated) {
			await goto(resolve('/'));
			return;
		}
		ready = true;
	});

	// Changing a Homebox collection invalidates its items, thumbnail blobs and
	// pending requests; results must not leak across user-selected collections.
	$effect(() => {
		const groupId = collectionStore.selectedId;
		if (!ready) return;
		void groupId;
		untrack(() => {
			detailGeneration++;
			selected = null;
			savedCount = 0;
			clearDetailPreview();
			void fetchPage(1, true);
		});
	});

	onDestroy(() => {
		listGeneration++;
		detailGeneration++;
		listController?.abort();
		clearDetailPreview();
		releaseThumbnails();
	});

	async function fetchPage(pageNumber: number, reset = false) {
		if (!reset && (isLoading || loadingMore || !hasMore)) return;
		if (reset) {
			listGeneration++;
			listController?.abort();
			listController = new AbortController();
			committedQuery = query.trim();
			inventory = [];
			total = 0;
			currentPage = 0;
			hasMore = false;
			message = '';
			loadingMore = false;
			isLoading = true;
			releaseThumbnails();
		} else {
			loadingMore = true;
			message = '';
		}
		const generation = listGeneration;
		const controller = listController;
		try {
			const response = await libraryImages.items(
				committedQuery,
				pageNumber,
				PAGE_SIZE,
				controller?.signal
			);
			if (generation !== listGeneration || controller?.signal.aborted) return;
			if (reset) {
				inventory = response.items;
			} else {
				// Items can move between pages if Homebox changes while browsing.
				const seen = new Set(inventory.map((item) => item.id));
				inventory = [...inventory, ...response.items.filter((item) => !seen.has(item.id))];
			}
			currentPage = pageNumber;
			total = response.total;
			hasMore = response.has_more;
		} catch (error) {
			if (generation !== listGeneration || controller?.signal.aborted) return;
			message = error instanceof Error ? error.message : 'Unable to load your inventory.';
		} finally {
			if (generation === listGeneration) {
				if (reset) isLoading = false;
				else loadingMore = false;
			}
		}
	}

	async function choose(item: LibraryItemSummary) {
		const generation = ++detailGeneration;
		loadingItem = true;
		message = '';
		clearDetailPreview();
		try {
			const detail = await libraryImages.item(item.id);
			if (generation !== detailGeneration) return;
			selected = detail;
			savedCount = 0;
			void refreshThumbnail();
		} catch (error) {
			if (generation !== detailGeneration) return;
			message = error instanceof Error ? error.message : 'Unable to open the item.';
		} finally {
			if (generation === detailGeneration) loadingItem = false;
		}
	}

	function backToLibrary() {
		detailGeneration++;
		selected = null;
		clearDetailPreview();
	}

	async function refreshThumbnail() {
		clearDetailPreview();
		const generation = detailImageGeneration;
		const item = selected;
		if (!item?.thumbnail_id) return;
		try {
			const result = await items.getThumbnail(item.id, item.thumbnail_id);
			if (generation !== detailImageGeneration || selected?.id !== item.id) {
				result.revoke();
				return;
			}
			revokeImage = result.revoke;
			imageUrl = result.url;
		} catch {
			// An unavailable attachment must not block image-search actions.
		}
	}

	async function attachLibraryPhoto(image: LibraryImageResult, primary: boolean) {
		const itemId = selected?.id;
		if (!itemId) throw new Error('Select an existing inventory item first.');
		const updated = await libraryImages.attach(itemId, image.id, primary);
		if (selected?.id !== itemId) return;
		selected = updated;
		savedCount++;
		if (primary) {
			invalidateItemThumbnail(itemId);
			inventory = inventory.map((item) =>
				item.id === itemId ? { ...item, thumbnail_id: updated.thumbnail_id } : item
			);
		}
		await refreshThumbnail();
		showToast(
			primary
				? 'New primary thumbnail saved in Homebox'
				: 'Catalogue photo added to Homebox gallery',
			'success'
		);
	}

	const isTiles = $derived(viewMode === 'medium' || viewMode === 'large');
</script>

<svelte:head><title>Library Images - Homebox Companion</title></svelte:head>

<div class="animate-in space-y-4 pb-32">
	<div class="flex items-center gap-2">
		<Images class="text-primary-400" size={26} />
		<div>
			<h1 class="text-h2 font-semibold text-neutral-100">Inventory Library Images</h1>
			<p class="text-body-sm text-neutral-400">
				Browse your items and choose catalogue photographs
			</p>
		</div>
	</div>

	{#if message}
		<p role="alert" class="rounded-lg bg-error-500/10 p-3 text-body-sm text-error-300">{message}</p>
	{/if}

	{#if selected}
		<button
			type="button"
			class="flex items-center gap-1 text-primary-400 text-body-sm"
			onclick={backToLibrary}
		>
			<ArrowLeft size={16} /> Back to item search
		</button>

		<div class="rounded-xl border border-neutral-700 bg-neutral-900 p-3">
			<div class="flex gap-3">
				{#if imageUrl}
					<img
						src={imageUrl}
						alt={selected.name}
						class="rounded-lg object-contain size-20 bg-neutral-800"
					/>
				{:else}
					<div class="flex items-center justify-center rounded-lg bg-neutral-800 size-20">
						<Images size={26} class="text-neutral-500" />
					</div>
				{/if}
				<div class="min-w-0 flex-1">
					<h2 class="font-semibold text-neutral-100">{selected.name}</h2>
					<p class="text-caption text-neutral-400">
						{[selected.manufacturer, selected.model_number].filter(Boolean).join(' · ') ||
							'No model information'}
					</p>
					<p class="text-caption text-neutral-500 line-clamp-2">{selected.description}</p>
				</div>
			</div>
			{#if savedCount > 0}
				<p class="mt-2 flex items-center gap-1 text-success-400 text-body-sm">
					<CheckCircle2 size={16} />
					{savedCount} photo{savedCount === 1 ? '' : 's'} imported this session
				</p>
			{/if}
		</div>
		{#key selected.id}
			<LibraryImagePicker
				name={selected.name}
				manufacturer={selected.manufacturer}
				modelNumber={selected.model_number}
				onSelect={attachLibraryPhoto}
			/>
		{/key}
	{:else}
		<form
			class="flex gap-2"
			onsubmit={(event) => {
				event.preventDefault();
				void fetchPage(1, true);
			}}
		>
			<input
				class="input min-w-0 flex-1"
				bind:value={query}
				aria-label="Find inventory item"
				placeholder="Search inventory name or model…"
				maxlength="120"
			/>
			<button
				type="submit"
				class="rounded-lg bg-primary-600 px-3 py-2 text-body-sm text-neutral-100"
				disabled={isLoading}
			>
				<Search size={18} />
				<span class="sr-only">Search inventory</span>
			</button>
		</form>

		<div
			class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-neutral-700 bg-neutral-900 px-3 py-2"
		>
			<p class="text-caption text-neutral-400">
				Showing {inventory.length} item{inventory.length === 1 ? '' : 's'}
				{#if total > inventory.length}<span> · {total} matching Homebox records</span>{/if}
			</p>
			<div class="flex items-center gap-2">
				<LayoutGrid size={16} class="text-neutral-400" aria-hidden="true" />
				<label for="library-display-mode" class="text-caption text-neutral-300">View</label>
				<select
					id="library-display-mode"
					aria-label="Library view"
					class="rounded-lg border border-neutral-600 bg-neutral-800 px-2 py-1.5 text-body-sm text-neutral-100"
					value={viewMode}
					onchange={(event) => setViewMode(event.currentTarget.value as LibraryView)}
				>
					<option value="compact">Compact list · no images</option>
					<option value="standard">Standard list · 40px</option>
					<option value="medium">Medium tiles</option>
					<option value="large">Large tiles</option>
				</select>
			</div>
		</div>

		{#if isLoading || loadingItem}
			<p class="flex items-center gap-2 py-6 text-body-sm text-neutral-400">
				<LoaderCircle size={16} class="animate-spin" /> Loading inventory…
			</p>
		{:else}
			<p class="text-caption text-neutral-500">
				Choose an item to look for catalogue images. Viewing items or photos does not initiate
				online searches.
			</p>

			<div
				data-library-view={viewMode}
				class={isTiles
					? 'grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4'
					: viewMode === 'compact'
						? 'space-y-1'
						: 'space-y-2'}
			>
				{#each inventory as item (item.id)}
					<button
						type="button"
						data-library-item={item.id}
						class={isTiles
							? 'flex min-w-0 flex-col gap-2 rounded-xl border border-neutral-700 bg-neutral-900 p-3 text-left text-neutral-200 hover:border-primary-500'
							: viewMode === 'compact'
								? 'flex w-full items-center justify-between gap-2 rounded-lg border border-neutral-700 bg-neutral-900 p-2 text-left text-neutral-200 hover:border-primary-500'
								: 'flex w-full min-h-16 items-center gap-3 rounded-xl border border-neutral-700 bg-neutral-900 p-2 text-left text-neutral-200 hover:border-primary-500'}
						onclick={() => choose(item)}
					>
						{#if viewMode !== 'compact'}
							<LibraryItemThumbnail
								{item}
								url={thumbnailUrl(item)}
								size={viewMode === 'medium'
									? 'medium'
									: viewMode === 'large'
										? 'large'
										: 'standard'}
								onVisible={requestThumbnail}
							/>
						{/if}
						<span class={isTiles ? 'block w-full min-w-0' : 'min-w-0 flex-1'}>
							<span
								class={isTiles ? 'block line-clamp-2 font-medium' : 'block truncate font-medium'}
							>
								{item.name}
							</span>
							<span
								class={isTiles
									? 'block line-clamp-2 text-caption text-neutral-500'
									: 'block truncate text-caption text-neutral-500'}
							>
								{item.model_number || item.description || 'Select to search product photos'}
							</span>
						</span>
						{#if !isTiles}<ChevronRight size={16} class="shrink-0 text-neutral-500" />{/if}
					</button>
				{/each}
			</div>

			{#if inventory.length === 0 && !message}
				<p class="py-6 text-center text-body-sm text-neutral-500">
					No matching items. Try a shorter search.
				</p>
			{/if}

			{#if hasMore}
				<button
					type="button"
					class="flex w-full items-center justify-center gap-2 rounded-xl border border-neutral-600 bg-neutral-800 p-3 text-body-sm font-medium text-neutral-100 hover:border-primary-500"
					disabled={loadingMore}
					onclick={() => fetchPage(currentPage + 1)}
				>
					{#if loadingMore}<LoaderCircle size={16} class="animate-spin" />Loading more…
					{:else}Load more items{/if}
				</button>
			{/if}
		{/if}
	{/if}
</div>
