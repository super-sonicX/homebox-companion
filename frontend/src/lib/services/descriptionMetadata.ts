/** Keep search descriptions aligned with metadata edits in the review form. */
import type { ReviewItem } from '$lib/types';

const METADATA_LABELS = {
	manufacturer: 'Manufacturer',
	model_number: 'Part/model number',
	serial_number: 'Serial number',
} as const;

function escapeRegex(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Full token boundaries, not arbitrary substrings (GE must not match 'voltage'). */
function identifierPattern(value: string): RegExp {
	return new RegExp(
		`(?<![\\p{L}\\p{N}_.-])${escapeRegex(value)}(?![\\p{L}\\p{N}_-]|\\.[\\p{L}\\p{N}_])`,
		'giu'
	);
}

function changeIdentifier(
	text: string,
	label: string,
	previous: string | null | undefined,
	next: string | null | undefined
): string {
	const oldValue = (previous ?? '').trim();
	const newValue = (next ?? '').trim();
	if (oldValue === newValue) return text;

	if (oldValue) {
		// The backend adds canonical "Label: value." sentences; remove those first
		// rather than leaving stale metadata alongside its corrected replacement.
		const generated = new RegExp(
			`(?:^|\\s+)${escapeRegex(label)}:\\s*${escapeRegex(oldValue)}\\.(?=\\s|$)`,
			'giu'
		);
		text = text.replace(generated, ' ').trim();
		// The AI might already have included the identifier in ordinary prose.
		// When a person corrects it, update that exact token rather than retaining a
		// known-wrong manufacturer or part number in the searchable description.
		text = text.replace(identifierPattern(oldValue), () => newValue);
	}

	if (newValue && !identifierPattern(newValue).test(text)) {
		text = `${text.trim()} ${label}: ${newValue}.`.trim();
	}
	return text.replace(/\s{2,}/g, ' ').trim();
}

const CUSTOM_IDENTIFIER_NAMES = [
	'part number',
	'part no',
	'mpn',
	'sku',
	'reference',
	'voltage',
	'current',
	'power rating',
	'wattage',
	'capacitance',
	'resistance',
	'dimensions',
	'diameter',
	'pitch',
	'connector type',
	'compatibility',
	'capacity',
];

const FINANCIAL_NAMES = [
	'price',
	'cost',
	'value',
	'amount',
	'payment',
	'invoice',
	'receipt',
	'shipping',
	'postage',
	'tax',
	'vat',
	'total',
	'discount',
];

/** Preserve user-edited description verbatim; sync only when metadata changes alone. */
export function reconcileDescriptionMetadata(
	current: ReviewItem,
	updates: Partial<ReviewItem>
): Partial<ReviewItem> {
	if (Object.prototype.hasOwnProperty.call(updates, 'description')) return updates;
	let description = current.description ?? '';
	let changed = false;
	for (const [field, label] of Object.entries(METADATA_LABELS)) {
		const key = field as keyof typeof METADATA_LABELS;
		if (!Object.prototype.hasOwnProperty.call(updates, key)) continue;
		const next = updates[key];
		if (next === current[key]) continue;
		description = changeIdentifier(description, label, current[key], next);
		changed = true;
	}
	if (Object.prototype.hasOwnProperty.call(updates, 'custom_fields')) {
		const oldFields = current.custom_fields ?? {};
		const newFields = updates.custom_fields ?? {};
		for (const key of new Set([...Object.keys(oldFields), ...Object.keys(newFields)])) {
			if (!CUSTOM_IDENTIFIER_NAMES.some((name) => key.toLowerCase().includes(name))) continue;
			if (FINANCIAL_NAMES.some((name) => key.toLowerCase().includes(name))) continue;
			if ((oldFields[key] ?? '') === (newFields[key] ?? '')) continue;
			description = changeIdentifier(description, key, oldFields[key], newFields[key]);
			changed = true;
		}
	}
	return changed ? { ...updates, description } : updates;
}
