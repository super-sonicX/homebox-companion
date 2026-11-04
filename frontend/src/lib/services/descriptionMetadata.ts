/** Keep search descriptions aligned with metadata edits in the review form. */
import type { DescriptionSource, ReviewItem } from '$lib/types';

const METADATA_LABELS = {
	manufacturer: 'Manufacturer',
	model_number: 'Part/model number',
	serial_number: 'Serial number',
} as const;

type IdentityField = keyof typeof METADATA_LABELS;
const IDENTITY_FIELDS = Object.keys(METADATA_LABELS) as IdentityField[];
const HSPACE = /[\p{Zs}\t]/u.source;
const LINE_BREAK = /(?:\r\n|[\r\n\v\f\u0085\u2028\u2029])/u;
const SAME_LINE_CONTENT = new RegExp(String.raw`${HSPACE}*[^\s\u0085]`, 'uy');
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
const CLAUSE_START = String.raw`(?:^${HSPACE}*|(?<=[.;!?])${HSPACE}+|${LINE_BREAK.source}${HSPACE}*)`;
const TECHNICAL_CLAUSE_START = `(?:,${HSPACE}*|${CLAUSE_START})`;
const IDENTITY_LABELS = new Set(Object.values(METADATA_LABELS).map((label) => label.toLowerCase()));

const HEADING_MARKS = /:|[\r\n\v\f\u0085\u2028\u2029]|(?<=[,.;!?])(?=[\p{Zs}\t])/gu;
const HISTORICAL_HEADING =
	/^(?:previous|original|former|compatible|alternative|historical|replacement)\b/iu;

/** Keep user-written headings and the notes after them out of narrative replacement. */
function narrativeBoundary(text: string, labels: readonly string[]): number {
	if (!text.includes(':')) return text.length;
	const protectedNames = new Set(
		labels.filter((label) => label.length <= text.length).map((label) => label.trim().toLowerCase())
	);
	let end = text.length;
	for (const leading of text.matchAll(new RegExp(TECHNICAL_CLAUSE_START, 'gu'))) {
		const offset = leading.index + leading[0].length;
		const colon = text.indexOf(':', offset);
		const label = colon < 0 ? '' : text.slice(offset, colon).trim().toLowerCase();
		if (protectedNames.has(label) && !(leading[0].startsWith(',') && IDENTITY_LABELS.has(label))) {
			end = leading.index;
			break;
		}
	}
	let start = 0;
	for (const mark of text.slice(0, end).matchAll(HEADING_MARKS)) {
		if (mark[0] === ':') {
			const heading = text.slice(start, mark.index).trim().replace(HORIZONTAL_SPACING, ' ');
			if (
				heading &&
				(HISTORICAL_HEADING.test(heading) ||
					!IDENTITY_CUES.some(({ pattern }) => pattern.test(heading)))
			)
				return start;
		}
		start = mark.index + mark[0].length;
	}
	return end;
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

	const clauseStart = identity ? CLAUSE_START : TECHNICAL_CLAUSE_START;
	const clausePattern = (value: string) =>
		new RegExp(
			`(${clauseStart})${escapeRegex(label)}${HSPACE}*:${HSPACE}*${escapeRegex(value)}(?:([.;!?]?${HSPACE}*[([])|([,.;!?](?=\\s|$)|(?<=[.;!?])(?=\\s|$)|(?=${HSPACE}*(?:${LINE_BREAK.source}|$))))`,
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
			(
				matched: string,
				leading: string,
				qualifier: string | undefined,
				punctuation: string,
				offset: number
			) => {
				if (qualifier) {
					if (!identity && newValue && !represented) {
						represented = true;
						return leading + label + ': ' + newValue + qualifier;
					}
					const suffix = matched.slice(leading.length + label.length);
					return leading + 'Previous ' + label[0].toLowerCase() + label.slice(1) + suffix;
				}
				if (!newValue || represented) {
					if (leading.startsWith(',')) return punctuation || oldValue.match(/[.;!?]$/)?.[0] || '';
					if (!LINE_BREAK.test(leading)) return '';
					SAME_LINE_CONTENT.lastIndex = offset + matched.length;
					return SAME_LINE_CONTENT.test(parts.metadata) ? leading : '';
				}
				represented = true;
				const end = punctuation || oldValue.match(/[.;!?]$/)?.[0] || '';
				const sharesEnd = end === ',' ? newValue.endsWith(',') : /[.;!?]$/.test(newValue);
				return `${leading}${label}: ${newValue}${sharesEnd ? '' : end}`;
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

const COMPATIBILITY_REFERENCE =
	/\b(?:(?:in)?compatible with|works with|for use with|replacement for|fits)\b/iu;
const FOR_TARGET = /\bfor\b(?! (?:example|instance)\b)/iu;
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

const SENTENCE_END = /[;!?\r\n\v\f\u0085\u2028\u2029]|\.(?=\s|$)/gu;
const ABBREVIATION = /\b(?:[a-z]|approx|no|nos|ref|rev|fig|inc|ltd|corp|co|dr|st|mr|mrs|ms|dia)$/iu;

function sentencePrefix(before: string): string {
	let start = 0;
	for (const end of before.matchAll(SENTENCE_END)) {
		if (end[0] !== '.' || !ABBREVIATION.test(before.slice(start, end.index)))
			start = end.index + end[0].length;
	}
	return before.slice(start);
}

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
	const sentence = sentencePrefix(before);
	if (
		COMPATIBILITY_REFERENCE.test(sentence) ||
		(field === 'manufacturer' && FOR_TARGET.test(sentence))
	) {
		const comma = sentence.lastIndexOf(',');
		const fieldPrefix = sentence.slice(comma + 1).trim();
		if (comma < 0 || cue?.pattern.exec(fieldPrefix)?.index !== 0) return false;
	}
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
