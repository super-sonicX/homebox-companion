/** Keep search descriptions aligned with metadata edits in the review form. */
import type { ReviewItem } from '$lib/types';

const METADATA_LABELS = {
	manufacturer: 'Manufacturer',
	model_number: 'Part/model number',
	serial_number: 'Serial number',
} as const;

type IdentityField = keyof typeof METADATA_LABELS;

export interface IdentityEdit {
	reviewId: string;
	field: IdentityField;
	previousValue: ReviewItem[IdentityField];
	description: ReviewItem['description'];
}

/** Only single-field input events continue a typing session. Bulk updates use their own description. */
export function editedIdentityField(updates: Partial<ReviewItem>): IdentityField | undefined {
	const keys = Object.keys(updates);
	const key = keys[0];
	return keys.length === 1 && Object.hasOwn(METADATA_LABELS, key)
		? (key as IdentityField)
		: undefined;
}

function escapeRegex(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Match a complete identifier: GE must not match "voltage" or "ABC-123" match "ABC-123.4". */
function identifierPattern(value: string): RegExp {
	return new RegExp(
		`(?<![\\p{L}\\p{N}_./-])${escapeRegex(value)}(?![\\p{L}\\p{N}_-]|[\\./][\\p{L}\\p{N}_])`,
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

/** Reject matches at the end of a longer protected heading: "Voltage" is
 * not the same field as "Activation Voltage". Match offsets include the
 * whitespace preceding the matched label. */
function belongsToLongerLabel(
	text: string,
	offset: number,
	label: string,
	protectedLabels: readonly string[]
): boolean {
	const lowerLabel = label.toLocaleLowerCase();
	const before = text.slice(0, offset).toLocaleLowerCase();
	return protectedLabels.some((other) => {
		const lowerOther = other.toLocaleLowerCase();
		if (lowerOther === lowerLabel || !lowerOther.endsWith(` ${lowerLabel}`)) return false;
		const prefix = lowerOther.slice(0, -lowerLabel.length - 1);
		return before.endsWith(prefix);
	});
}

type DescriptionParts = { narrative: string; metadata: string };

/** Update one field without promoting notes after a removed heading into editable narrative. */
function changeIdentifier(
	parts: DescriptionParts,
	label: string,
	previous: string | null | undefined,
	next: string | null | undefined,
	protectedLabels: readonly string[],
	isIdentity: boolean
): void {
	const oldValue = (previous ?? '').trim();
	const newValue = (next ?? '').trim();
	if (oldValue === newValue) return;

	const distinctive =
		/[\p{L}_/-]/u.test(oldValue) && oldValue.length >= (label === 'Manufacturer' ? 2 : 3);
	if (isIdentity && distinctive && newValue) {
		parts.narrative = parts.narrative.replace(identifierPattern(oldValue), () => newValue);
	}

	const clausePattern = (value: string) =>
		new RegExp(
			`(^|\\s+)${escapeRegex(label)}:[ \\t]*${escapeRegex(value)}([.;!?])(?=\\s|$)`,
			'giu'
		);
	let represented = Boolean(
		newValue &&
		((isIdentity && identifierPattern(newValue).test(parts.narrative)) ||
			Array.from(parts.metadata.matchAll(clausePattern(newValue))).some(
				(match) => !belongsToLongerLabel(parts.metadata, match.index, label, protectedLabels)
			))
	);
	if (oldValue) {
		parts.metadata = parts.metadata.replace(
			clausePattern(oldValue),
			(matched, leading: string, punctuation: string, offset: number) => {
				if (belongsToLongerLabel(parts.metadata, offset, label, protectedLabels)) return matched;
				if (!newValue || represented) return '';
				represented = true;
				return `${leading}${label}: ${newValue}${punctuation}`;
			}
		);
	}
	if (newValue && !represented) {
		const before = (parts.narrative + parts.metadata).trimEnd();
		const separator = !before ? '' : !isIdentity && !/[.;!?]$/.test(before) ? '. ' : ' ';
		parts.metadata = parts.metadata.trimEnd() + separator + `${label}: ${newValue}.`;
	}
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

const IDENTIFIER_NAME_PATTERN = new RegExp(
	`(?<![\\p{L}\\p{N}_])(?:${CUSTOM_IDENTIFIER_NAMES.map(escapeRegex).join('|')})(?![\\p{L}\\p{N}_])`,
	'iu'
);

const FINANCIAL_NAME_PATTERN =
	/(?<![\p{L}\p{N}_])(?:price|cost|amount|payment|invoice|receipt|shipping|postage|tax|vat|discount)(?![\p{L}\p{N}_])/iu;

/** Preserve explicit description edits; sync when metadata changes by itself. */
export function reconcileDescriptionMetadata(
	current: ReviewItem,
	updates: Partial<ReviewItem>
): Partial<ReviewItem> {
	if (Object.prototype.hasOwnProperty.call(updates, 'description')) return updates;
	const description = current.description ?? '';
	const protectedLabels = [
		...Object.values(METADATA_LABELS),
		...Object.keys(current.custom_fields ?? {}),
		...Object.keys(updates.custom_fields ?? {}),
	];
	const boundary = narrativeBoundary(description, protectedLabels);
	const parts = {
		narrative: description.slice(0, boundary),
		metadata: description.slice(boundary),
	};
	let changed = false;
	for (const [field, label] of Object.entries(METADATA_LABELS)) {
		const key = field as keyof typeof METADATA_LABELS;
		if (!Object.prototype.hasOwnProperty.call(updates, key)) continue;
		const next = updates[key];
		if (next === current[key]) continue;
		changeIdentifier(parts, label, current[key], next, protectedLabels, true);
		changed = true;
	}
	if (Object.prototype.hasOwnProperty.call(updates, 'custom_fields')) {
		const oldFields = current.custom_fields ?? {};
		const newFields = updates.custom_fields ?? {};
		for (const key of new Set([...Object.keys(oldFields), ...Object.keys(newFields)])) {
			if (!IDENTIFIER_NAME_PATTERN.test(key)) continue;
			if (FINANCIAL_NAME_PATTERN.test(key)) continue;
			if (/^[£$€]/.test((newFields[key] ?? oldFields[key] ?? '').trim())) continue;
			if ((oldFields[key] ?? '') === (newFields[key] ?? '')) continue;
			changeIdentifier(parts, key, oldFields[key], newFields[key], protectedLabels, false);
			changed = true;
		}
	}
	return changed ? { ...updates, description: (parts.narrative + parts.metadata).trim() } : updates;
}
