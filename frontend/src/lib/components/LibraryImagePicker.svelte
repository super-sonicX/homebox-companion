<script lang="ts">
	import { onMount } from 'svelte';
	import { Search, LoaderCircle, Images, ExternalLink, KeyRound, ArrowLeft } from '@lucide/svelte';
	import { libraryImages, type LibraryImageResult } from '$lib/api/libraryImages';

	interface Props {
		name: string;
		manufacturer?: string | null;
		modelNumber?: string | null;
		onSelect: (image: LibraryImageResult, primary: boolean) => Promise<void>;
	}

	let { name, manufacturer = null, modelNumber = null, onSelect }: Props = $props();
	type ImageProvider = 'serpapi' | 'ebay';
	let provider = $state<ImageProvider | null>(null);
	let serpapiConfigured = $state(false);
	let query = $state('');
	let results = $state<LibraryImageResult[]>([]);
	let searching = $state(false);
	let error = $state('');
	let hasSearched = $state(false);
	let selectedBusy = $state<string | null>(null);
	let showKeyInput = $state(false);
	let providerKey = $state('');
	let savingKey = $state(false);
	let keySaved = $state(false);
	let loadingProductId = $state<string | null>(null);
	let listingResults = $state<LibraryImageResult[]>([]);
	let showingListingPhotos = $state(false);
	let galleryTitle = $state('');

	onMount(() => {
		void initialise();
	});

	async function initialise() {
		// Preparing the search query and reading configuration must never spend API credits.
		query = [manufacturer, modelNumber, name].filter(Boolean).join(' ').slice(0, 180);
		try {
			serpapiConfigured = (await libraryImages.config()).serpapi_configured;
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to load search configuration';
		}
	}

	async function searchImages() {
		if (searching || !provider || !query.trim()) return;
		if (!serpapiConfigured) {
			showKeyInput = true;
			return;
		}
		searching = true;
		error = '';
		keySaved = false;
		results = [];
		listingResults = [];
		showingListingPhotos = false;
		loadingProductId = null;
		try {
			const response = await libraryImages.search(query.trim(), provider);
			results = response.results;
			hasSearched = true;
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Image search failed';
			hasSearched = true;
		} finally {
			searching = false;
		}
	}

	async function changeProvider(next: ImageProvider) {
		if (searching || savingKey || loadingProductId) return;
		provider = next;
		results = [];
		listingResults = [];
		showingListingPhotos = false;
		hasSearched = false;
		showKeyInput = false;
		keySaved = false;
		error = '';
		if (!serpapiConfigured) {
			showKeyInput = true;
			return;
		}
		// Clicking either of the two provider buttons initiates the search.
		await searchImages();
	}

	async function saveKey() {
		if (!providerKey.trim() || savingKey) return;
		savingKey = true;
		error = '';
		try {
			serpapiConfigured = (await libraryImages.setProviderKey(providerKey.trim()))
				.serpapi_configured;
			providerKey = '';
			showKeyInput = false;
			keySaved = true;
			// Saving a key is not permission to make a search request.
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to save SerpApi key';
		} finally {
			savingKey = false;
		}
	}

	async function openListingPhotos(item: LibraryImageResult) {
		if (!item.product_id || loadingProductId || selectedBusy) return;
		loadingProductId = item.product_id;
		error = '';
		try {
			// The eBay Product API uses a separate SerpApi search credit.
			// It is deliberately only called after clicking View listing photos.
			const detail = await libraryImages.ebayPhotos(item.product_id);
			if (!detail.results.length)
				throw new Error('No additional photographs found for this listing.');
			listingResults = results;
			results = detail.results;
			galleryTitle = detail.title;
			showingListingPhotos = true;
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to load listing photographs';
		} finally {
			loadingProductId = null;
		}
	}

	function backToListings() {
		results = listingResults;
		listingResults = [];
		showingListingPhotos = false;
		error = '';
	}

	async function selectImage(image: LibraryImageResult, primary: boolean) {
		if (selectedBusy) return;
		selectedBusy = image.id;
		error = '';
		try {
			await onSelect(image, primary);
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to import this image';
		} finally {
			selectedBusy = null;
		}
	}
</script>

<section class="space-y-3 rounded-xl border border-neutral-700 bg-neutral-900/70 p-3">
	<div class="flex items-center gap-2 text-neutral-100">
		<Images size={20} class="text-primary-400" />
		<h3 class="font-semibold">Library Images</h3>
	</div>
	<p class="text-caption text-neutral-400">
		Search using the item name and model number. Choose an online photograph to add to your gallery
		or use as the thumbnail; your own photos remain attached.
	</p>

	<div class="grid grid-cols-2 gap-2" role="group" aria-label="Image search provider">
		<button
			type="button"
			class="rounded-lg p-2 text-body-sm {provider === 'serpapi'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			disabled={searching || savingKey || loadingProductId !== null}
			onclick={() => changeProvider('serpapi')}>Google Images Lite</button
		>
		<button
			type="button"
			class="rounded-lg p-2 text-body-sm {provider === 'ebay'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			disabled={searching || savingKey || loadingProductId !== null}
			onclick={() => changeProvider('ebay')}>eBay Search</button
		>
	</div>
	<p class="text-caption text-neutral-500">
		Both searches use SerpApi. eBay Search shows the main picture of each matching UK listing.
	</p>

	{#if provider !== null && !serpapiConfigured}
		<div class="space-y-2 rounded-lg border border-neutral-700 p-3">
			<p class="text-body-sm text-neutral-300">
				Connect your SerpApi key once to use Google Images Lite and eBay Search. Both count against
				your SerpApi search allowance.
			</p>
			<a
				class="inline-flex items-center gap-1 text-caption text-primary-400 underline"
				href="https://serpapi.com/"
				target="_blank"
				rel="noopener noreferrer">SerpApi account <ExternalLink size={14} /></a
			>
			{#if showKeyInput}
				<div class="flex gap-2">
					<input
						type="password"
						class="input min-w-0 flex-1"
						autocomplete="off"
						placeholder="SerpApi API key"
						bind:value={providerKey}
					/>
					<button
						type="button"
						class="rounded-lg bg-primary-600 px-3 py-2 text-body-sm text-neutral-100"
						disabled={!providerKey.trim() || savingKey}
						onclick={saveKey}
					>
						{savingKey ? 'Saving…' : 'Save key'}
					</button>
				</div>
			{:else}
				<button
					type="button"
					class="inline-flex items-center gap-1 text-primary-400 text-body-sm"
					onclick={() => (showKeyInput = true)}><KeyRound size={16} /> Configure SerpApi</button
				>
			{/if}
		</div>
	{:else if provider !== null}
		{#if provider === 'ebay' && !showingListingPhotos}
			<p class="text-caption text-neutral-400">
				These are eBay sellers' main listing photos. Verify the model and condition before
				importing. Seller photos may be copyright-protected.
			</p>
		{/if}
		{#if keySaved}
			<p class="text-caption text-success-400" role="status">
				Search key saved. Click Search to retrieve images.
			</p>
		{/if}
		<form
			class="flex gap-2"
			onsubmit={(event) => {
				event.preventDefault();
				void searchImages();
			}}
		>
			<input
				class="input min-w-0 flex-1"
				maxlength="180"
				bind:value={query}
				aria-label="Library image search"
				placeholder="Item name and model number"
			/>
			<button
				type="submit"
				class="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-2 text-body-sm text-neutral-100"
				disabled={searching || loadingProductId !== null || !query.trim()}
			>
				{#if searching}<LoaderCircle size={16} class="animate-spin" />{:else}<Search
						size={16}
					/>{/if}
				Search
			</button>
		</form>
	{:else}
		<p
			class="rounded-lg border border-neutral-700/70 p-3 text-body-sm text-neutral-400"
			role="status"
		>
			Choose an image provider above to search. Opening an item does not start an image search.
		</p>
	{/if}

	{#if error}
		<p class="rounded-lg bg-error-500/10 p-2 text-body-sm text-error-300" role="alert">{error}</p>
	{/if}
	{#if searching}
		<p class="flex items-center gap-2 py-4 text-body-sm text-neutral-400">
			<LoaderCircle size={16} class="animate-spin" /> Searching online images…
		</p>
	{:else if hasSearched && results.length === 0 && !error}
		<p class="py-3 text-body-sm text-neutral-400">
			No matching images found. Try a shorter model name or the other search provider.
		</p>
	{/if}

	{#if results.length > 0}
		{#if showingListingPhotos}
			<div class="space-y-1">
				<button
					type="button"
					class="inline-flex items-center gap-1 text-primary-400 text-body-sm"
					onclick={backToListings}><ArrowLeft size={16} /> Back to eBay listings</button
				>
				<p class="text-caption text-neutral-300">{galleryTitle}</p>
				<p class="text-caption text-neutral-500">
					All photos from one listing. Select any photograph below.
				</p>
			</div>
		{:else}
			<p class="text-caption text-neutral-500">
				Showing {results.length} provider-ranked results, not verified exact-model matches. Check the
				source and permitted reuse before importing.
			</p>
		{/if}
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
			{#each results as item (item.id)}
				<div class="overflow-hidden rounded-xl border border-neutral-700 bg-neutral-800/60">
					<div class="aspect-square bg-neutral-800">
						<img
							src={item.thumbnail_url}
							alt={item.title}
							class="size-full object-contain"
							loading="lazy"
							referrerpolicy="no-referrer"
						/>
					</div>
					<div class="space-y-2 p-2">
						<p class="line-clamp-2 text-caption text-neutral-200" title={item.title}>
							{item.title}
						</p>
						<p class="truncate text-caption text-neutral-400">
							{item.source}{item.product_id && !showingListingPhotos
								? ' · #' + item.product_id
								: ''}
						</p>
						{#if item.source_url}
							<button
								type="button"
								onclick={() => window.open(item.source_url, '_blank', 'noopener,noreferrer')}
								class="flex items-center gap-1 text-primary-400 text-caption"
								>View source <ExternalLink size={12} /></button
							>
						{/if}
						{#if provider === 'ebay' && item.product_id && !showingListingPhotos}
							<button
								type="button"
								class="flex items-center gap-1 text-primary-400 text-caption"
								disabled={loadingProductId !== null || selectedBusy !== null}
								onclick={() => openListingPhotos(item)}
							>
								{#if loadingProductId === item.product_id}<LoaderCircle
										size={13}
										class="animate-spin"
									/>{/if}
								View listing photos (extra API search)
							</button>
						{/if}
						<div class="flex flex-col gap-1.5">
							<button
								type="button"
								class="rounded-lg border border-neutral-600 p-2 text-caption text-neutral-200"
								disabled={selectedBusy !== null || loadingProductId !== null}
								onclick={() => selectImage(item, false)}
							>
								{selectedBusy === item.id ? 'Importing…' : 'Add to gallery'}
							</button>
							<button
								type="button"
								class="rounded-lg bg-primary-600 p-2 text-caption font-medium text-neutral-100"
								disabled={selectedBusy !== null || loadingProductId !== null}
								onclick={() => selectImage(item, true)}
							>
								{selectedBusy === item.id ? 'Importing…' : 'Use as thumbnail'}
							</button>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</section>
