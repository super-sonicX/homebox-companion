<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Search, Images, LoaderCircle, CheckCircle2, ArrowLeft } from '@lucide/svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { getInitPromise } from '$lib/services/bootstrap';
	import { showToast } from '$lib/stores/ui.svelte';
	import { items } from '$lib/api/items';
	import {
		libraryImages,
		type LibraryItemDetail,
		type LibraryItemSummary,
		type LibraryImageResult,
	} from '$lib/api/libraryImages';
	import LibraryImagePicker from '$lib/components/LibraryImagePicker.svelte';

	let query = $state('');
	let inventory = $state<LibraryItemSummary[]>([]);
	let selected = $state<LibraryItemDetail | null>(null);
	let isLoading = $state(false);
	let loadingItem = $state(false);
	let message = $state('');
	let savedCount = $state(0);
	let imageUrl = $state<string | null>(null);
	let revokeImage: (() => void) | null = null;

	onMount(async () => {
		await getInitPromise();
		if (!authStore.isAuthenticated) {
			await goto(resolve('/'));
			return;
		}
		await loadInventory();
	});
	onDestroy(() => {
		revokeImage?.();
	});

	async function loadInventory() {
		isLoading = true;
		message = '';
		try {
			const response = await libraryImages.items(query);
			inventory = response.items;
		} catch (error) {
			message = error instanceof Error ? error.message : 'Unable to load your inventory.';
		} finally {
			isLoading = false;
		}
	}

	async function choose(item: LibraryItemSummary) {
		loadingItem = true;
		message = '';
		revokeImage?.();
		imageUrl = null;
		try {
			selected = await libraryImages.item(item.id);
			await refreshThumbnail();
		} catch (error) {
			message = error instanceof Error ? error.message : 'Unable to open the item.';
		} finally {
			loadingItem = false;
		}
	}

	async function refreshThumbnail() {
		revokeImage?.();
		revokeImage = null;
		imageUrl = null;
		if (!selected?.thumbnail_id) return;
		try {
			const result = await items.getThumbnail(selected.id, selected.thumbnail_id);
			revokeImage = result.revoke;
			imageUrl = result.url;
		} catch {
			// Inventory metadata remains usable even if the optional preview is unavailable.
		}
	}

	async function attachLibraryPhoto(image: LibraryImageResult, primary: boolean) {
		if (!selected) throw new Error('Select an existing inventory item first.');
		selected = await libraryImages.attach(selected.id, image.id, primary);
		savedCount++;
		await refreshThumbnail();
		showToast(
			primary
				? 'New primary thumbnail saved in Homebox'
				: 'Catalogue photo added to Homebox gallery',
			'success'
		);
	}
</script>

<svelte:head><title>Library Images - Homebox Companion</title></svelte:head>

<div class="animate-in space-y-4 pb-32">
	<div class="flex items-center gap-2">
		<Images class="text-primary-400" size={26} />
		<div>
			<h1 class="text-h2 font-semibold text-neutral-100">Inventory Library Images</h1>
			<p class="text-body-sm text-neutral-400">Find product photos for items already in Homebox</p>
		</div>
	</div>
	{#if message}
		<p role="alert" class="rounded-lg bg-error-500/10 p-3 text-body-sm text-error-300">{message}</p>
	{/if}

	{#if selected}
		<button
			type="button"
			class="flex items-center gap-1 text-primary-400 text-body-sm"
			onclick={() => {
				selected = null;
				revokeImage?.();
				imageUrl = null;
			}}
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
				void loadInventory();
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
				disabled={isLoading}><Search size={18} /></button
			>
		</form>
		{#if isLoading || loadingItem}
			<p class="flex items-center gap-2 text-body-sm text-neutral-400">
				<LoaderCircle size={16} class="animate-spin" /> Loading inventory…
			</p>
		{:else}
			<p class="text-caption text-neutral-500">
				Choose an existing item. No inventory changes are made until you explicitly import a photo.
			</p>
			<div class="space-y-2">
				{#each inventory as item (item.id)}
					<button
						type="button"
						class="flex w-full items-center justify-between gap-2 rounded-xl border border-neutral-700 bg-neutral-900 p-3 text-left text-neutral-200 hover:border-primary-500"
						onclick={() => choose(item)}
					>
						<span class="min-w-0">
							<span class="block truncate font-medium">{item.name}</span>
							<span class="block truncate text-caption text-neutral-500"
								>{item.model_number || item.description || 'Select to search product photos'}</span
							>
						</span>
						<Images size={18} class="shrink-0 text-primary-400" />
					</button>
				{/each}
				{#if inventory.length === 0}
					<p class="py-5 text-center text-body-sm text-neutral-500">
						No matching items. Try a shorter search.
					</p>
				{/if}
			</div>
		{/if}
	{/if}
</div>
