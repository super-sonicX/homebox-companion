<script lang="ts">
	import { onMount } from 'svelte';
	import { Search, LoaderCircle, Images, ExternalLink, KeyRound } from '@lucide/svelte';
	import { libraryImages, type LibraryImageResult } from '$lib/api/libraryImages';

	interface Props {
		name: string;
		manufacturer?: string | null;
		modelNumber?: string | null;
		onSelect: (image: LibraryImageResult, primary: boolean) => Promise<void>;
	}

	let { name, manufacturer = null, modelNumber = null, onSelect }: Props = $props();

	type ImageProvider = 'serpapi' | 'ebay' | 'google' | 'openverse';
	let provider = $state<ImageProvider | null>(null);
	let googleConfigured = $state(false);
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

	onMount(() => {
		void initialise();
	});

	async function initialise() {
		query = [manufacturer, modelNumber, name].filter(Boolean).join(' ').slice(0, 180);
		try {
			const config = await libraryImages.config();
			googleConfigured = config.google_configured;
			serpapiConfigured = config.serpapi_configured;
			// Opening an inventory item must never automatically consume search credits.
			// A provider-button click initiates the first search.
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to load image-search configuration';
		}
	}

	async function searchImages() {
		if (searching || !provider || !query.trim()) return;
		searching = true;
		error = '';
		keySaved = false;
		results = [];
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

	async function saveKey() {
		if (!providerKey.trim() || savingKey) return;
		savingKey = true;
		error = '';
		try {
			const config = await libraryImages.setProviderKey(
				provider === 'google' ? 'serper' : 'serpapi',
				providerKey.trim()
			);
			googleConfigured = config.google_configured;
			serpapiConfigured = config.serpapi_configured;
			providerKey = '';
			showKeyInput = false;
			keySaved = true;
			// Configuring a provider is not consent to run a paid search.
			// The user can click Search after saving the key.
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to save the provider key';
		} finally {
			savingKey = false;
		}
	}

	async function changeProvider(next: ImageProvider) {
		if (searching || savingKey) return;
		// A provider-button click always initiates a search if configured,
		// even when the same provider is clicked again.
		provider = next;
		results = [];
		hasSearched = false;
		showKeyInput = false;
		keySaved = false;
		error = '';
		const needsKey =
			next === 'google' ? !googleConfigured : next !== 'openverse' && !serpapiConfigured;
		if (needsKey) {
			showKeyInput = true;
			return;
		}
		await searchImages();
	}
</script>

<section class="space-y-3 rounded-xl border border-neutral-700 bg-neutral-900/70 p-3">
	<div class="flex items-center gap-2 text-neutral-100">
		<Images size={20} class="text-primary-400" />
		<h3 class="font-semibold">Library Images</h3>
	</div>
	<p class="text-caption text-neutral-400">
		Search by item name and model. Your own photos stay in the gallery. Check the model and source
		before importing.
	</p>

	<div class="grid grid-cols-2 gap-2">
		<button
			type="button"
			class="rounded-lg p-2 text-body-sm {provider === 'serpapi'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			disabled={searching || savingKey}
			onclick={() => changeProvider('serpapi')}>Google Images</button
		>
		<button
			type="button"
			class="rounded-lg p-2 text-body-sm {provider === 'ebay'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			disabled={searching || savingKey}
			onclick={() => changeProvider('ebay')}>eBay listings</button
		>
		<button
			type="button"
			class="rounded-lg p-2 text-body-sm {provider === 'google'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			disabled={searching || savingKey}
			onclick={() => changeProvider('google')}>Serper (existing)</button
		>
		<button
			type="button"
			class="rounded-lg p-2 text-body-sm {provider === 'openverse'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			disabled={searching || savingKey}
			onclick={() => changeProvider('openverse')}>Openverse · Free</button
		>
	</div>

	{#if (provider === 'google' && !googleConfigured) || ((provider === 'serpapi' || provider === 'ebay') && !serpapiConfigured)}
		<div class="rounded-lg border border-neutral-700 p-3 space-y-2">
			{#if provider === 'google'}
				<p class="text-body-sm text-neutral-300">
					This legacy search uses Serper.dev, which is currently experiencing registration failures.
					Choose Google Images above to use a separate SerpApi account instead.
				</p>
				<a
					class="inline-flex items-center gap-1 text-primary-400 text-caption underline"
					href="https://serper.dev/"
					target="_blank"
					rel="noopener noreferrer">Serper website <ExternalLink size={14} /></a
				>
			{:else}
				<p class="text-body-sm text-neutral-300">
					Google Images and eBay listing results use SerpApi, a different company from Serper.dev.
					The free SerpApi plan includes 250 searches per month. The eBay tab filters image search
					to eBay UK listings; no separate eBay API key is required.
				</p>
				<a
					class="inline-flex items-center gap-1 text-primary-400 text-caption underline"
					href="https://serpapi.com/"
					target="_blank"
					rel="noopener noreferrer">Create free SerpApi account <ExternalLink size={14} /></a
				>
			{/if}
			{#if showKeyInput}
				<div class="flex gap-2">
					<input
						type="password"
						class="input min-w-0 flex-1"
						placeholder={provider === 'google' ? 'Serper API key' : 'SerpApi API key'}
						autocomplete="off"
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
					class="flex items-center gap-1 text-primary-400 text-body-sm"
					onclick={() => (showKeyInput = true)}><KeyRound size={16} /> Configure search</button
				>
			{/if}
		</div>
	{:else if provider !== null}
		{#if provider === 'ebay'}
			<p class="text-caption text-neutral-400">
				Searching image results from eBay UK listing pages. Seller photos may be copyrighted and may
				show used or different-condition products. Check the exact model before importing.
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
				aria-label="Library image search"
				placeholder="Item name and model number"
				maxlength="180"
				bind:value={query}
			/>
			<button
				type="submit"
				class="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-2 text-neutral-100 text-body-sm"
				disabled={searching || !query.trim()}
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
		<p class="text-body-sm text-neutral-400 py-3">
			No matching images found. Try a shorter model name or Google Images for less common products.
		</p>
	{/if}

	{#if results.length > 0}
		<p class="text-caption text-neutral-500">
			Showing {results.length} ranked matches. These are search results, not verified variants; check
			the source. Copyright/licensing may restrict reuse.
		</p>
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
							{item.source}{item.license ? ' · ' + item.license : ''}
						</p>
						{#if item.source_url}
							<button
								type="button"
								onclick={() => window.open(item.source_url, '_blank', 'noopener,noreferrer')}
								class="flex items-center gap-1 text-primary-400 text-caption"
								>View source <ExternalLink size={12} /></button
							>
						{/if}
						{#if item.attribution}
							<p class="line-clamp-2 text-xxs text-neutral-400" title={item.attribution}>
								Credit: {item.attribution}
							</p>
						{/if}
						<div class="flex flex-col gap-1.5">
							<button
								type="button"
								class="rounded-lg border border-neutral-600 p-2 text-caption text-neutral-200"
								disabled={selectedBusy !== null}
								onclick={() => selectImage(item, false)}
							>
								{selectedBusy === item.id ? 'Importing…' : 'Add to gallery'}
							</button>
							<button
								type="button"
								class="rounded-lg bg-primary-600 p-2 text-caption font-medium text-neutral-100"
								disabled={selectedBusy !== null}
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
