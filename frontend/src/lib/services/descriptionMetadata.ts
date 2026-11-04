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

// Keep this delimiter in sync with description_policy.CLAUSE_START.
const CLAUSE_START = String.raw`(?:^[ \t]*|(?<=[.;!?])[ \t]+|\r?\n[ \t]*)`;

/** Keep user-written headings and the notes after them out of narrative replacement. */
function narrativeBoundary(text: string, labels: readonly string[]): number {
	const headings = [...labels.map(escapeRegex), String.raw`[^:.;!?\r\n]+`];
	const match = new RegExp(`${CLAUSE_START}(?:${headings.join('|')}):`, 'iu').exec(text);
	return match?.index ?? text.length;
}

type DescriptionParts = { narrative: string; metadata: string };

/** Update one field without promoting notes after a removed heading into editable narrative. */
function changeIdentifier(
	parts: DescriptionParts,
	label: string,
	previous: string | null | undefined,
	next: string | null | undefined,
	identity?: { field: IdentityField; name: string }
): void {
	const oldValue = (previous ?? '').trim();
	const newValue = (next ?? '').trim();
	if (oldValue === newValue) return;

	const clausePattern = (value: string) =>
		new RegExp(
			`(${CLAUSE_START})${escapeRegex(label)}:[ \\t]*${escapeRegex(value)}([.;!?])(?=\\s|$)`,
			'giu'
		);
	let represented = Boolean(
		newValue &&
		((identity &&
			Array.from(parts.narrative.matchAll(identifierPattern(newValue))).some(
				(match) =>
					!/^\d+$/.test(newValue) ||
					numericIdentityContext(
						parts.narrative,
						match.index,
						newValue,
						identity.field,
						identity.name
					)
			)) ||
			clausePattern(newValue).test(parts.metadata))
	);
	if (oldValue) {
		parts.metadata = parts.metadata.replace(
			clausePattern(oldValue),
			(_matched, leading: string, punctuation: string) => {
				if (!newValue || represented) return '';
				represented = true;
				return `${leading}${label}: ${newValue}${punctuation}`;
			}
		);
	}
	if (newValue && !represented) {
		const before = (parts.narrative + parts.metadata).trimEnd();
		const separator = !before ? '' : !/[.;!?]$/.test(before) ? '. ' : ' ';
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

/** A short number needs an explicit model/serial cue; a leading part designation can precede the product name. */
function numericIdentityContext(
	text: string,
	offset: number,
	value: string,
	field: IdentityField,
	name: string
): boolean {
	const before = text.slice(0, offset);
	const cue =
		field === 'serial_number'
			? /\b(?:serial(?:\s+(?:number|no\.?))?|s\/n)\s*[#:=]?\s*$/iu
			: /\b(?:model(?:\s+(?:number|no\.?))?|part(?:\s+(?:number|no\.?))?|mpn|p\/n)\s*[#:=]?\s*$/iu;
	if (field === 'manufacturer') return false;
	if (cue.test(before)) return true;
	if (
		field !== 'model_number' ||
		value.length < 3 ||
		!/^(?:(?:an?|the)\s+)?$/iu.test(before.trimStart())
	)
		return false;
	const following = text.slice(offset + value.length).trimStart();
	const product = name.trim().replace(/^(?:an?|the)\s+/iu, '');
	// Only infer a designation from a product name or an explicit electronics part type.
	return (
		(Boolean(product) &&
			new RegExp('^' + escapeRegex(product) + '(?![\\p{L}\\p{N}_])', 'iu').test(following)) ||
		/^(?:(?:linear|voltage|switching)\s+regulator|integrated circuit)\b/iu.test(following)
	);
}

/** Replace matching original tokens once. A new brand can itself be the old model. */
function reconcileNarrative(
	narrative: string,
	source: DescriptionSource,
	next: DescriptionSource,
	itemName: string
): string {
	const identities = (Object.keys(METADATA_LABELS) as IdentityField[])
		.map((field) => ({
			field,
			original: (source[field] ?? '').trim(),
			replacement: (next[field] ?? '').trim(),
		}))
		.filter(
			({ field, original }) =>
				/^\d+$/.test(original) ||
				(/[\p{L}_/-]/u.test(original) && original.length >= (field === 'manufacturer' ? 2 : 3))
		);
	if (!identities.length) return narrative;
	const pattern = identifierPattern(
		...identities.map(({ original }) => original).sort((a, b) => b.length - a.length)
	);
	return narrative.replace(pattern, (matched, offset: number) => {
		const owners = identities.filter(
			({ field, original }) =>
				original.toLocaleLowerCase() === matched.toLocaleLowerCase() &&
				(!/^\d+$/.test(original) ||
					numericIdentityContext(narrative, offset, original, field, itemName))
		);
		const [first] = owners;
		if (!first?.replacement || first.original === first.replacement) return matched;
		return owners.every((owner) => owner.replacement === first.replacement)
			? first.replacement
			: matched;
	});
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
		narrative: reconcileNarrative(description.slice(0, boundary), source, next, next.name),
		metadata: description.slice(boundary),
	};
	let changed = false;
	for (const [field, label] of Object.entries(METADATA_LABELS)) {
		const key = field as keyof typeof METADATA_LABELS;
		if (next[key] === source[key]) continue;
		changeIdentifier(parts, label, source[key], next[key], { field: key, name: next.name });
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
			changeIdentifier(parts, key, oldFields[key], newFields[key]);
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
