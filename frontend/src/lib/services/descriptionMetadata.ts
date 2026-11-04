/** Keep search descriptions aligned with metadata edits in the review form. */
import type { DescriptionSource, ReviewItem } from '$lib/types';

const METADATA_LABELS = {
	manufacturer: 'Manufacturer',
	model_number: 'Part/model number',
	serial_number: 'Serial number',
} as const;

type IdentityField = keyof typeof METADATA_LABELS;

function escapeRegex(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Match a complete identifier: GE must not match "voltage" or "ABC-123" match "ABC-123.4". */
function identifierPattern(...values: string[]): RegExp {
	return new RegExp(
		`(?<![\\p{L}\\p{N}_./-])(?:${values.map(escapeRegex).join('|')})(?![\\p{L}\\p{N}_-]|[\\./][\\p{L}\\p{N}_])`,
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

/** Replace matching original tokens once. A new brand can itself be the old model. */
function reconcileNarrative(
	narrative: string,
	source: DescriptionSource,
	next: DescriptionSource
): string {
	const replacements = new Map<string, string | null>();
	for (const field of Object.keys(METADATA_LABELS) as IdentityField[]) {
		const oldValue = (source[field] ?? '').trim();
		if (!/[\p{L}_/-]/u.test(oldValue) || oldValue.length < (field === 'manufacturer' ? 2 : 3))
			continue;
		const key = oldValue.toLocaleLowerCase();
		const newValue = (next[field] ?? '').trim();
		const replacement = newValue && newValue !== oldValue ? newValue : null;
		replacements.set(
			key,
			replacements.has(key) && replacements.get(key) !== replacement ? null : replacement
		);
	}
	if (!replacements.size) return narrative;
	const pattern = identifierPattern(
		...Array.from(replacements.keys()).sort((a, b) => b.length - a.length)
	);
	return narrative.replace(
		pattern,
		(matched) => replacements.get(matched.toLocaleLowerCase()) ?? matched
	);
}

/** Preserve explicit description edits; re-render automatic edits from the last authored description. */
export function reconcileDescriptionMetadata(
	current: ReviewItem,
	updates: Partial<ReviewItem>
): Partial<ReviewItem> {
	if (Object.hasOwn(updates, 'description')) {
		return current.descriptionSource ? { ...updates, descriptionSource: undefined } : updates;
	}
	if (
		!Object.keys(updates).some(
			(key) => key === 'custom_fields' || Object.hasOwn(METADATA_LABELS, key)
		)
	)
		return updates;
	const source = current.descriptionSource ?? {
		description: current.description,
		manufacturer: current.manufacturer,
		model_number: current.model_number,
		serial_number: current.serial_number,
		custom_fields: current.custom_fields ? { ...current.custom_fields } : current.custom_fields,
	};
	const next = { ...current, ...updates };
	const description = source.description ?? '';
	const protectedLabels = [
		...Object.values(METADATA_LABELS),
		...Object.keys(source.custom_fields ?? {}),
		...Object.keys(next.custom_fields ?? {}),
	];
	const boundary = narrativeBoundary(description, protectedLabels);
	const parts = {
		narrative: reconcileNarrative(description.slice(0, boundary), source, next),
		metadata: description.slice(boundary),
	};
	let changed = false;
	for (const [field, label] of Object.entries(METADATA_LABELS)) {
		const key = field as keyof typeof METADATA_LABELS;
		if (next[key] === source[key]) continue;
		changeIdentifier(parts, label, source[key], next[key], protectedLabels, true);
		changed = true;
	}
	if (source.custom_fields || next.custom_fields) {
		const oldFields = source.custom_fields ?? {};
		const newFields = next.custom_fields ?? {};
		for (const key of new Set([...Object.keys(oldFields), ...Object.keys(newFields)])) {
			if (!IDENTIFIER_NAME_PATTERN.test(key)) continue;
			if (FINANCIAL_NAME_PATTERN.test(key)) continue;
			if (/^[£$€]/.test((newFields[key] ?? oldFields[key] ?? '').trim())) continue;
			if ((oldFields[key] ?? '') === (newFields[key] ?? '')) continue;
			changeIdentifier(parts, key, oldFields[key], newFields[key], protectedLabels, false);
			changed = true;
		}
	}
	if (!changed && !current.descriptionSource) return updates;
	return {
		...updates,
		descriptionSource: changed ? source : undefined,
		description: changed ? (parts.narrative + parts.metadata).trim() : source.description,
	};
}
