<script lang="ts">
	import { ImageIcon } from '@lucide/svelte';
	import type { LibraryItemSummary } from '$lib/api/libraryImages';

	interface Props {
		item: LibraryItemSummary;
		url?: string | null;
		size: 'standard' | 'medium' | 'large';
		onVisible: (item: LibraryItemSummary) => void;
	}

	let { item, url = null, size, onVisible }: Props = $props();
	let target: HTMLDivElement;

	// Only request an image when its tile approaches the viewport.
	// Requests and blob URLs are pooled and cached by the parent page, rather than per tile.
	$effect(() => {
		const attachmentId = item.thumbnail_id;
		const displayedUrl = url;
		// Re-observe after cache eviction; old items must reload when scrolled back into view.
		if (!attachmentId || !target || displayedUrl) return;
		const itemRef = item;
		if (typeof IntersectionObserver === 'undefined') {
			onVisible(itemRef);
			return;
		}
		const observer = new IntersectionObserver(
			(entries) => {
				if (entries.some((entry) => entry.isIntersecting)) {
					onVisible(itemRef);
					observer.disconnect();
				}
			},
			{ rootMargin: '180px 0px' }
		);
		observer.observe(target);
		return () => observer.disconnect();
	});

	const sizeClass = $derived(
		size === 'standard' ? 'size-10' : size === 'medium' ? 'h-28 w-full' : 'h-44 w-full lg:h-48'
	);
</script>

<div
	bind:this={target}
	data-library-thumbnail
	data-item-id={item.id}
	class="flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-neutral-800 {sizeClass}"
>
	{#if url}
		<img src={url} alt="" class="object-contain size-full" loading="lazy" />
	{:else}
		<ImageIcon
			size={size === 'standard' ? 18 : size === 'medium' ? 28 : 36}
			class="text-neutral-600"
			aria-hidden="true"
			strokeWidth={1.5}
		/>
	{/if}
</div>
