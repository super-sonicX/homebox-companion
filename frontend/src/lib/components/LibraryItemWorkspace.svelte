<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		Camera,
		Upload,
		ImagePlus,
		Images,
		LoaderCircle,
		Pencil,
		FileText,
		ArrowLeft,
		ArrowRight,
		Trash2,
		Star,
		Expand,
		X,
		CheckCircle2,
	} from '@lucide/svelte';
	import { items } from '$lib/api/items';
	import {
		libraryImages,
		type LibraryPhoto,
		type LibraryImageResult,
		type LibraryItemDetail,
		type LibraryItemEdits,
	} from '$lib/api/libraryImages';
	import { showToast } from '$lib/stores/ui.svelte';
	import LibraryGalleryPhoto from './LibraryGalleryPhoto.svelte';
	import LibraryImagePicker from './LibraryImagePicker.svelte';

	interface Props {
		item: LibraryItemDetail;
		headerImageUrl?: string | null;
		onUpdated: (item: LibraryItemDetail) => void;
	}

	let { item, headerImageUrl = null, onUpdated }: Props = $props();
	let detailsOpen = $state(false);
	let editing = $state(false);
	let onlineImagesOpen = $state(false);
	let busy = $state('');
	let error = $state('');
	let savedCount = $state(0);
	let uploadInput: HTMLInputElement;
	let cameraInput: HTMLInputElement;
	let draft = $state<LibraryItemEdits>({
		name: '',
		description: '',
		quantity: 1,
		manufacturer: '',
		model_number: '',
		serial_number: '',
		notes: '',
		purchase_from: '',
		purchase_price: null,
	});
	let priceText = $state('');

	let previewPhotoId = $state<string | null>(null);
	let previewUrl = $state<string | null>(null);
	let previewLoading = $state(false);
	let releasePreview: (() => void) | null = null;
	let previewGeneration = 0;

	const photos = $derived.by(() => {
		const existing = item.attachments ?? [];
		const order = item.gallery_order ?? existing.map((p) => p.id);
		const positions = new Map(order.map((id, index) => [id, index]));
		return [...existing].sort(
			(a, b) =>
				(positions.get(a.id) ?? Number.MAX_SAFE_INTEGER) -
				(positions.get(b.id) ?? Number.MAX_SAFE_INTEGER)
		);
	});

	function isPrimary(photo: LibraryPhoto): boolean {
		return photo.primary || photo.id === item.thumbnail_id;
	}

	function beginEdit() {
		draft = {
			name: item.name ?? '',
			description: item.description ?? '',
			quantity: item.quantity ?? 1,
			manufacturer: item.manufacturer ?? '',
			model_number: item.model_number ?? '',
			serial_number: item.serial_number ?? '',
			notes: item.notes ?? '',
			purchase_from: item.purchase_from ?? '',
			purchase_price: item.purchase_price ?? null,
			expected_updated_at: item.updated_at || undefined,
		};
		priceText = item.purchase_price == null ? '' : String(item.purchase_price);
		error = '';
		editing = true;
		detailsOpen = false;
	}

	async function saveDetails() {
		if (busy || !draft.name.trim()) {
			error = 'Item title is required.';
			return;
		}
		if (!Number.isFinite(draft.quantity) || draft.quantity < 0) {
			error = 'Quantity must be a valid number of zero or greater.';
			return;
		}
		if (priceText.trim() && (!Number.isFinite(Number(priceText)) || Number(priceText) < 0)) {
			error = 'Purchase price must be a positive amount or blank.';
			return;
		}
		busy = 'saving';
		error = '';
		try {
			const updated = await libraryImages.editDetails(item.id, {
				...draft,
				name: draft.name.trim(),
				purchase_price: priceText.trim() ? Number(priceText) : null,
			});
			onUpdated(updated);
			editing = false;
			detailsOpen = true;
			showToast('Item details updated in Homebox', 'success');
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to save item details';
		} finally {
			busy = '';
		}
	}

	async function makePrimary(photo: LibraryPhoto) {
		if (busy || isPrimary(photo)) return;
		busy = photo.id;
		error = '';
		try {
			onUpdated(await libraryImages.setPrimary(item.id, photo.id));
			showToast('Primary Homebox photograph updated', 'success');
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to set the primary photograph';
		} finally {
			busy = '';
		}
	}

	async function movePhoto(photoId: string, direction: -1 | 1) {
		if (busy) return;
		const photoIds = photos.map((photo) => photo.id);
		const index = photoIds.indexOf(photoId);
		const next = index + direction;
		if (index < 0 || next < 0 || next >= photoIds.length) return;
		[photoIds[index], photoIds[next]] = [photoIds[next], photoIds[index]];
		busy = photoId;
		error = '';
		try {
			onUpdated(await libraryImages.reorderPhotos(item.id, photoIds));
			showToast('Photo order saved in Companion', 'success');
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to reorder the photographs';
		} finally {
			busy = '';
		}
	}

	async function deletePhoto(photo: LibraryPhoto) {
		if (busy) return;
		const warning = isPrimary(photo)
			? 'Delete the current primary photograph permanently from Homebox? This cannot be undone.'
			: 'Delete this photograph permanently from Homebox? This cannot be undone.';
		if (!window.confirm(warning)) return;
		busy = photo.id;
		error = '';
		try {
			closeFullPreview();
			onUpdated(await libraryImages.deletePhoto(item.id, photo.id));
			showToast('Photo deleted from Homebox', 'success');
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to delete the photograph';
		} finally {
			busy = '';
		}
	}

	async function uploadFiles(source: FileList | null) {
		const files = source ? Array.from(source) : [];
		if (!files.length || busy) return;
		busy = 'uploading';
		error = '';
		let completed = 0;
		try {
			for (const file of files) {
				if (file.size === 0 || file.size > 10 * 1024 * 1024) {
					throw new Error('Each photo must be between 1 byte and 10 MB.');
				}
				if (file.type && !file.type.startsWith('image/')) {
					throw new Error('Please select an image file.');
				}
				await items.uploadAttachment(item.id, file);
				completed++;
			}
		} catch (ex) {
			error = ex instanceof Error ? ex.message : 'Unable to upload photograph';
		} finally {
			if (completed > 0) {
				try {
					onUpdated(await libraryImages.item(item.id));
					showToast(
						completed + ' photograph' + (completed === 1 ? '' : 's') + ' uploaded',
						'success'
					);
				} catch (ex) {
					error =
						ex instanceof Error ? ex.message : 'Photos uploaded; reload this item to see them.';
				}
			}
			busy = '';
		}
	}

	async function addOnlineImage(image: LibraryImageResult, primary: boolean) {
		if (busy) throw new Error('Another edit is in progress.');
		busy = image.id;
		error = '';
		try {
			onUpdated(await libraryImages.attach(item.id, image.id, primary));
			savedCount++;
			showToast(
				primary ? 'Catalogue image set as primary' : 'Catalogue image added to gallery',
				'success'
			);
		} finally {
			busy = '';
		}
	}

	function closeFullPreview() {
		previewGeneration++;
		releasePreview?.();
		releasePreview = null;
		previewUrl = null;
		previewPhotoId = null;
		previewLoading = false;
	}

	async function viewFullPhoto(photo: LibraryPhoto) {
		closeFullPreview();
		const generation = previewGeneration;
		previewPhotoId = photo.id;
		previewLoading = true;
		try {
			const image = await items.getThumbnail(item.id, photo.id);
			if (generation !== previewGeneration) {
				image.revoke();
				return;
			}
			releasePreview = image.revoke;
			previewUrl = image.url;
		} catch (ex) {
			if (generation === previewGeneration) {
				error = ex instanceof Error ? ex.message : 'Unable to view full-resolution photograph';
			}
		} finally {
			if (generation === previewGeneration) previewLoading = false;
		}
	}

	onDestroy(closeFullPreview);
</script>

<section class="space-y-4" data-item-workspace>
	<div class="rounded-xl border border-neutral-700 bg-neutral-900 p-3">
		<div class="flex items-start gap-3">
			{#if headerImageUrl}
				<img
					src={headerImageUrl}
					alt=""
					class="size-20 shrink-0 rounded-lg bg-neutral-800 object-contain"
				/>
			{:else}
				<div class="flex size-20 shrink-0 items-center justify-center rounded-lg bg-neutral-800">
					<Images size={26} class="text-neutral-500" />
				</div>
			{/if}
			<div class="min-w-0 flex-1 space-y-1">
				<h2 class="font-semibold text-neutral-100">{item.name}</h2>
				<p class="text-caption text-neutral-400">
					{item.manufacturer || 'Unknown manufacturer'}
					{#if item.model_number}
						· {item.model_number}{/if}
				</p>
				<p class="text-caption text-neutral-500">Quantity: {item.quantity ?? 1}</p>
			</div>
		</div>
		<div class="mt-3 flex flex-wrap gap-2">
			<button
				type="button"
				data-show-details
				class="flex items-center gap-1 rounded-lg border border-neutral-600 px-3 py-2 text-body-sm text-neutral-200"
				onclick={() => {
					detailsOpen = !detailsOpen;
					editing = false;
				}}
			>
				<FileText size={16} />
				{detailsOpen && !editing ? 'Hide details' : 'Details'}
			</button>
			<button
				type="button"
				data-edit-item
				class="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-2 text-body-sm font-medium text-neutral-100"
				disabled={!!busy}
				onclick={beginEdit}
			>
				<Pencil size={16} /> Edit
			</button>
		</div>

		{#if editing}
			<form
				data-item-edit
				class="mt-4 space-y-3 border-t border-neutral-700 pt-4"
				onsubmit={(event) => {
					event.preventDefault();
					void saveDetails();
				}}
			>
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
					<label class="block text-body-sm text-neutral-300"
						>Item title *
						<input class="input mt-1 w-full" required maxlength="255" bind:value={draft.name} />
					</label>
					<label class="block text-body-sm text-neutral-300"
						>Quantity
						<input
							type="number"
							min="0"
							step="any"
							class="input mt-1 w-full"
							required
							bind:value={draft.quantity}
						/>
					</label>
					<label class="block text-body-sm text-neutral-300"
						>Manufacturer
						<input class="input mt-1 w-full" maxlength="255" bind:value={draft.manufacturer} />
					</label>
					<label class="block text-body-sm text-neutral-300"
						>Model / product number
						<input class="input mt-1 w-full" maxlength="255" bind:value={draft.model_number} />
					</label>
					<label class="block text-body-sm text-neutral-300"
						>Serial number
						<input class="input mt-1 w-full" maxlength="255" bind:value={draft.serial_number} />
					</label>
					<label class="block text-body-sm text-neutral-300"
						>Purchased from
						<input class="input mt-1 w-full" maxlength="255" bind:value={draft.purchase_from} />
					</label>
					<label class="block text-body-sm text-neutral-300"
						>Purchase price
						<input
							type="text"
							inputmode="decimal"
							class="input mt-1 w-full"
							placeholder="Not recorded"
							bind:value={priceText}
						/>
					</label>
				</div>
				<label class="block text-body-sm text-neutral-300"
					>Description
					<textarea
						class="input mt-1 w-full"
						rows="3"
						maxlength="1000"
						bind:value={draft.description}></textarea>
				</label>
				<label class="block text-body-sm text-neutral-300"
					>Notes
					<textarea class="input mt-1 w-full" rows="3" maxlength="10000" bind:value={draft.notes}
					></textarea>
				</label>
				<p class="text-caption text-neutral-500">
					Location, containers, tags, warranty dates and custom fields will be preserved unchanged.
				</p>
				<div class="flex gap-2">
					<button
						type="submit"
						data-save-item
						class="rounded-lg bg-primary-600 px-4 py-2 text-body-sm font-semibold text-neutral-100"
						disabled={!!busy || !draft.name.trim()}
					>
						{busy === 'saving' ? 'Saving…' : 'Save changes'}
					</button>
					<button
						type="button"
						class="rounded-lg border border-neutral-600 px-4 py-2 text-body-sm text-neutral-300"
						disabled={!!busy}
						onclick={() => (editing = false)}>Cancel</button
					>
				</div>
			</form>
		{:else if detailsOpen}
			<dl
				data-item-details
				class="mt-4 grid grid-cols-1 gap-x-4 gap-y-2 border-t border-neutral-700 pt-3 text-body-sm sm:grid-cols-2"
			>
				<div>
					<dt class="text-neutral-500">Description</dt>
					<dd class="whitespace-pre-wrap text-neutral-200">{item.description || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Quantity</dt>
					<dd class="text-neutral-200">{item.quantity ?? 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Manufacturer</dt>
					<dd class="text-neutral-200">{item.manufacturer || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Model number</dt>
					<dd class="text-neutral-200">{item.model_number || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Serial number</dt>
					<dd class="text-neutral-200">{item.serial_number || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Asset ID</dt>
					<dd class="text-neutral-200">{item.asset_id || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Stored in / location</dt>
					<dd class="text-neutral-200">
						{[item.location, item.parent].filter(Boolean).join(' · ') || 'Not recorded'}
					</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Tags</dt>
					<dd class="text-neutral-200">{item.tags?.join(', ') || 'None'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Purchase price</dt>
					<dd class="text-neutral-200">{item.purchase_price ?? 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Purchased from</dt>
					<dd class="text-neutral-200">{item.purchase_from || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Purchase date</dt>
					<dd class="text-neutral-200">{item.purchase_date || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Warranty expires</dt>
					<dd class="text-neutral-200">{item.warranty_expires || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Warranty details</dt>
					<dd class="text-neutral-200">{item.warranty_details || 'Not recorded'}</dd>
				</div>
				<div>
					<dt class="text-neutral-500">Last modified</dt>
					<dd class="text-neutral-200">{item.updated_at || 'Not recorded'}</dd>
				</div>
				<div class="sm:col-span-2">
					<dt class="text-neutral-500">Notes</dt>
					<dd class="whitespace-pre-wrap text-neutral-200">{item.notes || 'Not recorded'}</dd>
				</div>
			</dl>
		{/if}
	</div>

	{#if error}
		<p class="rounded-lg bg-error-500/10 p-3 text-body-sm text-error-300" role="alert">{error}</p>
	{/if}

	<div
		class="space-y-3 rounded-xl border border-neutral-700 bg-neutral-900 p-3"
		data-library-gallery
	>
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div>
				<h3 class="font-semibold text-neutral-100">Your item photographs ({photos.length})</h3>
				<p class="text-caption text-neutral-400">
					All images already attached to this Homebox item
				</p>
			</div>
			<div class="flex gap-2">
				<button
					type="button"
					class="flex items-center gap-1 rounded-lg border border-neutral-600 p-2 text-caption text-neutral-200"
					disabled={!!busy}
					onclick={() => uploadInput?.click()}><Upload size={15} /> Upload</button
				>
				<button
					type="button"
					class="flex items-center gap-1 rounded-lg border border-neutral-600 p-2 text-caption text-neutral-200"
					disabled={!!busy}
					onclick={() => cameraInput?.click()}><Camera size={15} /> Camera</button
				>
				<input
					class="hidden"
					type="file"
					accept="image/*"
					multiple
					bind:this={uploadInput}
					aria-label="Upload item photos"
					onchange={(event) => {
						void uploadFiles(event.currentTarget.files);
						event.currentTarget.value = '';
					}}
				/>
				<input
					class="hidden"
					type="file"
					accept="image/*"
					capture="environment"
					bind:this={cameraInput}
					aria-label="Capture item photo"
					onchange={(event) => {
						void uploadFiles(event.currentTarget.files);
						event.currentTarget.value = '';
					}}
				/>
			</div>
		</div>
		{#if photos.length === 0}
			<p class="rounded-lg bg-neutral-800 p-4 text-center text-body-sm text-neutral-400">
				No photos attached yet. Upload a photograph, take a picture or find a catalogue image below.
			</p>
		{:else}
			<p class="text-caption text-neutral-500">
				Move buttons reorder this gallery in Companion. Homebox itself may display a different
				order. Delete permanently removes the chosen Homebox photograph.
			</p>
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
				{#each photos as photo, index (photo.id)}
					<div
						data-gallery-photo={photo.id}
						class="space-y-2 rounded-xl border border-neutral-700 bg-neutral-900/70 p-2"
					>
						<LibraryGalleryPhoto itemId={item.id} photoId={photo.id} title={photo.title} />
						<div class="flex items-center justify-between gap-1">
							<span class="truncate text-caption text-neutral-300"
								>{photo.title || 'Photo ' + (index + 1)}</span
							>
							{#if isPrimary(photo)}
								<span class="text-caption text-primary-400">Primary</span>
							{/if}
						</div>
						<div class="flex flex-wrap gap-1">
							<button
								type="button"
								title="View full photo"
								aria-label={'View full photo ' + (index + 1)}
								class="rounded-md bg-neutral-800 p-2 text-neutral-300"
								onclick={() => viewFullPhoto(photo)}><Expand size={15} /></button
							>
							<button
								type="button"
								title="Move earlier"
								aria-label={'Move photo ' + (index + 1) + ' earlier'}
								class="rounded-md bg-neutral-800 p-2 text-neutral-300"
								disabled={!!busy || index === 0}
								onclick={() => movePhoto(photo.id, -1)}><ArrowLeft size={15} /></button
							>
							<button
								type="button"
								title="Move later"
								aria-label={'Move photo ' + (index + 1) + ' later'}
								class="rounded-md bg-neutral-800 p-2 text-neutral-300"
								disabled={!!busy || index === photos.length - 1}
								onclick={() => movePhoto(photo.id, 1)}><ArrowRight size={15} /></button
							>
							<button
								type="button"
								title="Make primary"
								aria-label={'Make photo ' + (index + 1) + ' primary'}
								class="rounded-md bg-neutral-800 p-2 text-primary-400"
								disabled={!!busy || isPrimary(photo)}
								onclick={() => makePrimary(photo)}><Star size={15} /></button
							>
							<button
								type="button"
								title="Delete photo"
								aria-label={'Delete photo ' + (index + 1)}
								class="rounded-md bg-neutral-800 p-2 text-error-300"
								disabled={!!busy}
								onclick={() => deletePhoto(photo)}><Trash2 size={15} /></button
							>
						</div>
					</div>
				{/each}
			</div>
		{/if}
		{#if busy === 'uploading'}
			<p class="flex items-center gap-2 text-caption text-neutral-400">
				<LoaderCircle size={16} class="animate-spin" /> Uploading photographs…
			</p>
		{/if}
	</div>

	{#if previewPhotoId}
		<div data-photo-preview class="rounded-xl border border-neutral-700 bg-neutral-900 p-3">
			<div class="flex items-center justify-between gap-3">
				<p class="text-body-sm text-neutral-200">Full photograph</p>
				<button
					type="button"
					class="flex items-center gap-1 text-primary-400 text-caption"
					onclick={closeFullPreview}><X size={15} /> Close</button
				>
			</div>
			{#if previewUrl}
				<img
					src={previewUrl}
					alt="Selected full-resolution inventory photograph"
					class="mt-3 max-h-[65vh] w-full object-contain"
				/>
			{:else if previewLoading}
				<p class="mt-3 text-caption text-neutral-400">Loading photograph…</p>
			{/if}
		</div>
	{/if}

	<div class="space-y-3">
		<button
			type="button"
			class="flex w-full items-center justify-center gap-2 rounded-xl border border-neutral-700 bg-neutral-900 p-3 text-body-sm font-medium text-neutral-100"
			onclick={() => (onlineImagesOpen = !onlineImagesOpen)}
		>
			<ImagePlus size={18} />
			{onlineImagesOpen ? 'Hide library image search' : 'Find additional library images'}
		</button>
		{#if savedCount > 0}
			<p class="flex items-center gap-1 text-caption text-success-400">
				<CheckCircle2 size={16} />
				{savedCount} catalogue photograph{savedCount === 1 ? '' : 's'} added this session
			</p>
		{/if}
		{#if onlineImagesOpen}
			{#key item.id}
				<LibraryImagePicker
					name={item.name}
					manufacturer={item.manufacturer}
					modelNumber={item.model_number}
					onSelect={addOnlineImage}
				/>
			{/key}
		{/if}
	</div>
</section>
