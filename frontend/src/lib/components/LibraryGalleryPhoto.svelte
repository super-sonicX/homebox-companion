<script lang="ts">
	import { onDestroy } from 'svelte';
	import { ImageIcon } from '@lucide/svelte';
	import { libraryImages } from '$lib/api/libraryImages';

	interface Props {
		itemId: string;
		photoId: string;
		title?: string;
	}

	let { itemId, photoId, title = '' }: Props = $props();
	let imageUrl = $state<string | null>(null);
	let placeholder: HTMLDivElement;
	let release: (() => void) | null = null;

	// Keep authenticated URLs out of HTML and revoke all blob URLs on teardown.
	$effect(() => {
		const item = itemId;
		const photo = photoId;
		if (!placeholder) return;
		const controller = new AbortController();
		let observer: IntersectionObserver | null = null;

		async function fetchPhoto() {
			try {
				const result = await libraryImages.thumbnail(item, photo, controller.signal);
				if (controller.signal.aborted) {
					result.revoke();
					return;
				}
				release?.();
				release = result.revoke;
				imageUrl = result.url;
			} catch {
				// A missing or damaged photo should display a placeholder, not break the gallery.
			}
		}

		if (typeof IntersectionObserver === 'undefined') {
			void fetchPhoto();
		} else {
			observer = new IntersectionObserver(
				(entries) => {
					if (entries.some((entry) => entry.isIntersecting)) {
						observer?.disconnect();
						void fetchPhoto();
					}
				},
				{ rootMargin: '180px 0px' }
			);
			observer.observe(placeholder);
		}
		return () => {
			controller.abort();
			observer?.disconnect();
			release?.();
			release = null;
			imageUrl = null;
		};
	});

	onDestroy(() => release?.());
</script>

<div
	bind:this={placeholder}
	data-library-photo={photoId}
	class="flex aspect-square items-center justify-center overflow-hidden rounded-lg bg-neutral-800"
>
	{#if imageUrl}
		<img
			src={imageUrl}
			alt={title || 'Inventory photograph'}
			class="size-full object-contain"
			loading="lazy"
		/>
	{:else}
		<ImageIcon size={32} strokeWidth={1.3} class="text-neutral-600" />
	{/if}
</div>
