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

/** Match a complete identifier: GE must not match "voltage" or "ABC-123" match "ABC-123.4". */
function identifierPattern(value: string): RegExp {
	return new RegExp(
		`(?<![\\p{L}\\p{N}_.-])${escapeRegex(value)}(?![\\p{L}\\p{N}_-]|[\\./][\\p{L}\\p{N}_])`,
		'giu'
	);
}

/** The functional narrative precedes generated metadata clauses. Never edit
 * another field's clause, even if its value matches the edited field. */
function narrativeBoundary(text: string, protectedLabels: readonly string[]): number {
	let first = text.length;
	for (const label of new Set(protectedLabels)) {
		const heading = new RegExp(`(?:^|\\s+)${escapeRegex(label)}:\\s*`, 'iu');
		const match = heading.exec(text);
		if (match && match.index < first) first = match.index;
	}
	return first;
}

function changeIdentifier(
	text: string,
	label: string,
	previous: string | null | undefined,
	next: string | null | undefined,
	protectedLabels: readonly string[]
): string {
	const oldValue = (previous ?? '').trim();
	const newValue = (next ?? '').trim();
	if (oldValue === newValue) return text;

	if (oldValue) {
		// Remove only the canonical clause belonging to the edited field.
		const generated = new RegExp(
			`(?:^|\\s+)${escapeRegex(label)}:\\s*${escapeRegex(oldValue)}\\.(?=\\s|$)`,
			'giu'
		);
		text = text.replace(generated, ' ').trim();
		// If the AI also mentioned the old value in functional prose, update it.
		// Everything from the first known metadata heading onward is protected.
		// Technical readings such as Capacity=1 must never change unrelated
		// prose (e.g. "1 port"). Only distinct identity values may be updated
		// outside their own labelled clauses; numeric-only values are ambiguous.
		const isIdentity = ['Manufacturer', 'Part/model number', 'Serial number'].includes(label);
		const distinctive =
			/[\p{L}_/-]/u.test(oldValue) && oldValue.length >= (label === 'Manufacturer' ? 2 : 3);
		if (isIdentity && distinctive) {
			const boundary = narrativeBoundary(text, protectedLabels);
			text =
				text.slice(0, boundary).replace(identifierPattern(oldValue), () => newValue) +
				text.slice(boundary);
		}
	}

	const boundary = narrativeBoundary(text, protectedLabels);
	const mentionedInNarrative =
		newValue && identifierPattern(newValue).test(text.slice(0, boundary));
	const matchingOwnClause =
		newValue &&
		new RegExp(
			`(?:^|\\s+)${escapeRegex(label)}:\\s*${escapeRegex(newValue)}\\.(?=\\s|$)`,
			'iu'
		).test(text);
	if (newValue && !mentionedInNarrative && !matchingOwnClause) {
		text = `${text.trim()} ${label}: ${newValue}.`.trim();
	}
	return text.replace(/[ \t]{2,}/g, ' ').trim();
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

const FINANCIAL_NAME_PATTERN =
	/(?<![\p{L}\p{N}_])(?:price|cost|amount|payment|invoice|receipt|shipping|postage|tax|vat|discount)(?![\p{L}\p{N}_])/iu;

/** Preserve explicit description edits; sync when metadata changes by itself. */
export function reconcileDescriptionMetadata(
	current: ReviewItem,
	updates: Partial<ReviewItem>
): Partial<ReviewItem> {
	if (Object.prototype.hasOwnProperty.call(updates, 'description')) return updates;
	let description = current.description ?? '';
	const protectedLabels = [
		...Object.values(METADATA_LABELS),
		...Object.keys(current.custom_fields ?? {}),
		...Object.keys(updates.custom_fields ?? {}),
	];
	let changed = false;
	for (const [field, label] of Object.entries(METADATA_LABELS)) {
		const key = field as keyof typeof METADATA_LABELS;
		if (!Object.prototype.hasOwnProperty.call(updates, key)) continue;
		const next = updates[key];
		if (next === current[key]) continue;
		description = changeIdentifier(description, label, current[key], next, protectedLabels);
		changed = true;
	}
	if (Object.prototype.hasOwnProperty.call(updates, 'custom_fields')) {
		const oldFields = current.custom_fields ?? {};
		const newFields = updates.custom_fields ?? {};
		for (const key of new Set([...Object.keys(oldFields), ...Object.keys(newFields)])) {
			if (!CUSTOM_IDENTIFIER_NAMES.some((name) => key.toLowerCase().includes(name))) continue;
			if (FINANCIAL_NAME_PATTERN.test(key)) continue;
			if (/^[£$€]/.test((newFields[key] ?? oldFields[key] ?? '').trim())) continue;
			if ((oldFields[key] ?? '') === (newFields[key] ?? '')) continue;
			description = changeIdentifier(
				description,
				key,
				oldFields[key],
				newFields[key],
				protectedLabels
			);
			changed = true;
		}
	}
	return changed ? { ...updates, description } : updates;
}
