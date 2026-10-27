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

	let provider = $state<'google' | 'openverse'>('openverse');
	let googleConfigured = $state(false);
	let query = $state('');
	let results = $state<LibraryImageResult[]>([]);
	let searching = $state(false);
	let error = $state('');
	let hasSearched = $state(false);
	let selectedBusy = $state<string | null>(null);
	let showKeyInput = $state(false);
	let providerKey = $state('');
	let savingKey = $state(false);

	onMount(() => {
		void initialise();
	});

	async function initialise() {
		query = [manufacturer, modelNumber, name].filter(Boolean).join(' ').slice(0, 180);
		try {
			googleConfigured = (await libraryImages.config()).google_configured;
			provider = googleConfigured ? 'google' : 'openverse';
			await searchImages();
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to load image-search configuration';
		}
	}

	async function searchImages() {
		if (searching || !query.trim()) return;
		searching = true;
		error = '';
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
			const config = await libraryImages.setGoogleKey(providerKey.trim());
			googleConfigured = config.google_configured;
			providerKey = '';
			showKeyInput = false;
			provider = 'google';
			await searchImages();
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to save the provider key';
		} finally {
			savingKey = false;
		}
	}

	async function changeProvider(next: 'google' | 'openverse') {
		if (next === provider) return;
		provider = next;
		results = [];
		hasSearched = false;
		if (next === 'google' && !googleConfigured) {
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

	<div class="flex gap-2">
		<button
			type="button"
			class="rounded-lg px-3 py-2 text-body-sm {provider === 'google'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			onclick={() => changeProvider('google')}>Google Images</button
		>
		<button
			type="button"
			class="rounded-lg px-3 py-2 text-body-sm {provider === 'openverse'
				? 'bg-primary-600 text-neutral-100'
				: 'bg-neutral-800 text-neutral-300'}"
			onclick={() => changeProvider('openverse')}>Openverse · Free</button
		>
	</div>

	{#if provider === 'google' && !googleConfigured}
		<div class="rounded-lg border border-neutral-700 p-3 space-y-2">
			<p class="text-body-sm text-neutral-300">
				Google Images results require a Serper API key. Serper advertises free trial searches. Your
				key is stored on the Companion server.
			</p>
			<a
				class="inline-flex items-center gap-1 text-primary-400 text-caption underline"
				href="https://serper.dev/"
				target="_blank"
				rel="noopener noreferrer">Get a Serper search key <ExternalLink size={14} /></a
			>
			{#if showKeyInput}
				<div class="flex gap-2">
					<input
						type="password"
						class="input min-w-0 flex-1"
						placeholder="Paste Serper API key"
						autocomplete="off"
						bind:value={providerKey}
					/>
					<button
						type="button"
						class="rounded-lg bg-primary-600 px-3 py-2 text-body-sm text-neutral-100"
						disabled={!providerKey.trim() || savingKey}
						onclick={saveKey}
					>
						{savingKey ? 'Saving…' : 'Save'}
					</button>
				</div>
			{:else}
				<button
					type="button"
					class="flex items-center gap-1 text-primary-400 text-body-sm"
					onclick={() => (showKeyInput = true)}
					><KeyRound size={16} /> Configure Google search</button
				>
			{/if}
		</div>
	{:else}
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
