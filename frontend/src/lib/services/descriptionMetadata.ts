/** Keep search descriptions aligned with metadata edits in the review form. */
import type { DescriptionSource, ReviewItem } from '$lib/types';

const METADATA_LABELS = {
	manufacturer: 'Manufacturer',
	model_number: 'Part/model number',
	serial_number: 'Serial number',
} as const;

type IdentityField = keyof typeof METADATA_LABELS;
const IDENTITY_FIELDS = Object.keys(METADATA_LABELS) as IdentityField[];
const HORIZONTAL_SPACING = /[\p{Zs}\t]+/gu;

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
	const pattern = new RegExp(`${CLAUSE_START}(${headings.join('|')})[ \\t]*:`, 'giu');
	const protectedNames = new Set(labels.map((label) => label.trim().toLowerCase()));
	for (const match of text.matchAll(pattern)) {
		const heading = match[1].trim().toLowerCase();
		const cue = heading
			.slice(heading.lastIndexOf(',') + 1)
			.trim()
			.replace(HORIZONTAL_SPACING, ' ');
		if (
			protectedNames.has(heading) ||
			!IDENTITY_CUES.some(({ pattern }) => pattern.exec(cue)?.index === 0)
		)
			return match.index;
	}
	return text.length;
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
			`(${CLAUSE_START})${escapeRegex(label)}[ \\t]*:[ \\t]*${escapeRegex(value)}(?:([.;!?]?[ \\t]*[([])|([.;!?](?=\\s|$)|(?<=[.;!?])(?=\\s|$)|(?=[ \\t]*(?:\\r?\\n|$))))`,
			'giu'
		);
	let represented = Boolean(
		newValue &&
		((identity &&
			Array.from(parts.narrative.matchAll(identifierPattern(newValue))).some((match) =>
				narrativeIdentityMatches(
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
			(matched: string, leading: string, qualifier: string | undefined, punctuation: string) => {
				if (qualifier) {
					if (!identity && newValue && !represented) {
						represented = true;
						return leading + label + ': ' + newValue + qualifier;
					}
					const suffix = matched.slice(leading.length + label.length);
					return leading + 'Previous ' + label[0].toLowerCase() + label.slice(1) + suffix;
				}
				if (!newValue || represented) return '';
				represented = true;
				const end = punctuation || oldValue.match(/[.;!?]$/)?.[0] || '';
				return `${leading}${label}: ${newValue}${/[.;!?]$/.test(newValue) ? '' : end}`;
			}
		);
	}
	if (newValue && !represented) {
		const before = (parts.narrative + parts.metadata).trimEnd();
		const separator = !before ? '' : !/[.;!?]$/.test(before) ? '. ' : ' ';
		const end = /[.;!?]$/.test(newValue) ? '' : '.';
		parts.metadata = parts.metadata.trimEnd() + separator + `${label}: ${newValue}${end}`;
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

const IDENTITY_CUES: ReadonlyArray<{ field: IdentityField; pattern: RegExp }> = [
	{
		field: 'manufacturer',
		pattern: /\b(?:manufacturer|brand(?: name)?|made by|manufactured by)[ \t]*[#:=]?[ \t]*$/iu,
	},
	{
		field: 'model_number',
		pattern: /\b(?:(?:model|part)(?:[ \t]+(?:number|no\.?))?|mpn|p\/n)[ \t]*[#:=]?[ \t]*$/iu,
	},
	{
		field: 'serial_number',
		pattern: /\b(?:serial(?:[ \t]+(?:number|no\.?))?|s\/n)[ \t]*[#:=]?[ \t]*$/iu,
	},
];

/** Disambiguate short identities and numbers using their field cue or a leading product designation. */
function narrativeIdentityMatches(
	text: string,
	offset: number,
	value: string,
	field: IdentityField,
	name: string
): boolean {
	const before = text.slice(0, offset).replace(HORIZONTAL_SPACING, ' ');
	const cue = IDENTITY_CUES.find(({ pattern }) => pattern.test(before));
	if (cue) return cue.field === field;
	if (/[\p{L}_/-]/u.test(value) && value.length >= (field === 'manufacturer' ? 2 : 3)) return true;
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
	const identities = IDENTITY_FIELDS.map((field) => ({
		field,
		original: (source[field] ?? '').trim(),
		replacement: (next[field] ?? '').trim(),
	})).filter(({ original }) => original.length > 0);
	if (!identities.length) return narrative;
	const pattern = identifierPattern(
		...identities.map(({ original }) => original).sort((a, b) => b.length - a.length)
	);
	return narrative.replace(pattern, (matched, offset: number) => {
		const owners = identities.filter(
			({ field, original }) =>
				original.toLocaleLowerCase() === matched.toLocaleLowerCase() &&
				narrativeIdentityMatches(narrative, offset, original, field, itemName)
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
	if (Object.hasOwn(updates, 'description') && updates.description !== current.description) {
		return current.descriptionSource ? { ...updates, descriptionSource: undefined } : updates;
	}
	const next = { ...current, ...updates };
	const customChanged =
		next.custom_fields !== current.custom_fields &&
		Object.keys({ ...current.custom_fields, ...next.custom_fields }).some(
			(key) => current.custom_fields?.[key] !== next.custom_fields?.[key]
		);
	if (!customChanged && !IDENTITY_FIELDS.some((field) => current[field] !== next[field])) {
		return Object.hasOwn(updates, 'descriptionSource')
			? { ...updates, descriptionSource: current.descriptionSource }
			: updates;
	}
	const source = current.descriptionSource ?? {
		name: current.name,
		description: current.description,
		manufacturer: current.manufacturer,
		model_number: current.model_number,
		serial_number: current.serial_number,
		custom_fields: current.custom_fields ? { ...current.custom_fields } : current.custom_fields,
	};
	const sourceName = source.name ?? current.name;
	const description = source.description ?? '';
	const protectedLabels = [
		...Object.values(METADATA_LABELS),
		...Object.keys(source.custom_fields ?? {}),
		...Object.keys(next.custom_fields ?? {}),
	];
	const boundary = narrativeBoundary(description, protectedLabels);
	const parts = {
		narrative: reconcileNarrative(description.slice(0, boundary), source, next, sourceName),
		metadata: description.slice(boundary),
	};
	let changed = false;
	for (const [field, label] of Object.entries(METADATA_LABELS)) {
		const key = field as keyof typeof METADATA_LABELS;
		if (next[key] === source[key]) continue;
		changeIdentifier(parts, label, source[key], next[key], { field: key, name: sourceName });
		changed = true;
	}
	if (source.custom_fields || next.custom_fields) {
		const oldFields = source.custom_fields ?? {};
		const newFields = next.custom_fields ?? {};
		for (const key of new Set([...Object.keys(oldFields), ...Object.keys(newFields)])) {
			if (!IDENTIFIER_NAME_PATTERN.test(key)) continue;
			if (FINANCIAL_NAME_PATTERN.test(key)) continue;
			const oldValue = oldFields[key]?.trim() ?? '';
			const newValue = newFields[key]?.trim() ?? '';
			const replacement = /^[£$€]/.test(newValue) ? '' : newValue;
			if (oldValue === newValue || (!oldValue && !replacement)) continue;
			changeIdentifier(parts, key, oldValue, replacement);
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
