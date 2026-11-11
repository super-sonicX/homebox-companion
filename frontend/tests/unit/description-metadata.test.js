import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = readFileSync(
	new URL('../../src/lib/services/descriptionMetadata.ts', import.meta.url),
	'utf8'
);
const { outputText } = ts.transpileModule(source, {
	compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
runInNewContext(outputText, { exports, RegExp, Object, Set });
const { reconcileDescriptionMetadata } = exports;
const current = (fields) => ({ name: 'Bumper', quantity: 1, sourceImageIndex: 0, ...fields });

test('changing detected metadata replaces old generated fields', () => {
	const previous = current({
		description: 'Front bumper brackets. Manufacturer: WrongCo. Part/model number: OLD-123.',
		manufacturer: 'WrongCo',
		model_number: 'OLD-123',
	});
	const changes = reconcileDescriptionMetadata(previous, {
		manufacturer: 'RightCo',
		model_number: 'NEW-456',
	});
	assert.match(changes.description, /Manufacturer: RightCo/);
	assert.match(changes.description, /Part\/model number: NEW-456/);
	assert.doesNotMatch(changes.description, /WrongCo|OLD-123/);
});

test('correcting natural prose replaces exact old identifier', () => {
	const previous = current({
		description: 'WrongCo brackets, model OLD-123.',
		manufacturer: 'WrongCo',
		model_number: 'OLD-123',
	});
	const changes = reconcileDescriptionMetadata(previous, {
		manufacturer: 'RightCo',
		model_number: 'NEW-456',
	});
	assert.match(changes.description, /RightCo brackets, model NEW-456/);
	assert.doesNotMatch(changes.description, /WrongCo|OLD-123/);
});

test('clearing model removes stale generated part number', () => {
	const previous = current({ description: 'Part/model number: BAD-999.', model_number: 'BAD-999' });
	const changes = reconcileDescriptionMetadata(previous, { model_number: null });
	assert.equal(changes.description, '');
});

test('short manufacturer must not match inside unrelated words', () => {
	const previous = current({ description: 'A voltage regulator.', manufacturer: null });
	const changes = reconcileDescriptionMetadata(previous, { manufacturer: 'GE' });
	assert.match(changes.description, /Manufacturer: GE/);
});

test('custom part number and technical rating changes are reflected', () => {
	const previous = current({
		description: 'Connector. Supplier Part Number: OLD-1. Voltage: 12V.',
		custom_fields: { 'Supplier Part Number': 'OLD-1', Voltage: '12V' },
	});
	const changes = reconcileDescriptionMetadata(previous, {
		custom_fields: { 'Supplier Part Number': 'NEW-2', Voltage: '24V' },
	});
	assert.match(changes.description, /Supplier Part Number: NEW-2/);
	assert.match(changes.description, /Voltage: 24V/);
	assert.doesNotMatch(changes.description, /OLD-1|12V/);
});

test('explicit description edits take priority over generated content', () => {
	const previous = current({ description: 'Previous description.', manufacturer: 'Old' });
	const changes = reconcileDescriptionMetadata(previous, {
		description: 'User text.',
		manufacturer: 'New',
	});
	assert.deepEqual({ ...changes }, { description: 'User text.', manufacturer: 'New' });
});

test('custom reference price cannot overwrite useful description', () => {
	const previous = current({
		description: 'DC-DC converter module.',
		custom_fields: { 'Reference Price': '£3', 'Supplier Reference': 'REF-123' },
	});
	const changes = reconcileDescriptionMetadata(previous, {
		custom_fields: { 'Reference Price': '£4', 'Supplier Reference': 'REF-456' },
	});
	assert.match(changes.description, /Supplier Reference: REF-456/);
	assert.doesNotMatch(changes.description, /£4|REF-123/);
});

test('decimal or version suffix is not mistaken for a complete identifier', () => {
	const previous = current({ description: 'Alternative model ABC-123.4.', model_number: null });
	const changes = reconcileDescriptionMetadata(previous, { model_number: 'ABC-123' });
	assert.match(changes.description, /Part\/model number: ABC-123\./);
});

test('metadata correction preserves user-entered paragraph breaks', () => {
	const previous = current({
		description: 'Product with context.\n\nManufacturer: WrongCo.\n\nImportant second paragraph.',
		manufacturer: 'WrongCo',
	});
	const changes = reconcileDescriptionMetadata(previous, { manufacturer: 'RightCo' });
	assert.match(changes.description, /\n\nImportant second paragraph/);
	assert.match(changes.description, /Manufacturer: RightCo/);
});

test('editing current leaves voltage intact when both fields shared the same value', () => {
	const previous = current({
		description: 'Power supply. Voltage: 12. Current: 12.',
		custom_fields: { Voltage: '12', Current: '12' },
	});
	const changes = reconcileDescriptionMetadata(previous, {
		custom_fields: { Voltage: '12', Current: '24' },
	});
	assert.match(changes.description, /Voltage: 12\./);
	assert.match(changes.description, /Current: 24\./);
	assert.doesNotMatch(changes.description, /Voltage: 24\./);
	assert.doesNotMatch(changes.description, /Current: 12\./);
});

test('changing numeric capacity preserves unrelated port count in prose', () => {
	const previous = current({
		description: 'Converter with 1 port. Capacity: 1.',
		custom_fields: { Capacity: '1' },
	});
	const changes = reconcileDescriptionMetadata(previous, { custom_fields: { Capacity: '2' } });
	assert.match(changes.description, /with 1 port/);
	assert.match(changes.description, /Capacity: 2\./);
	assert.doesNotMatch(changes.description, /with 2 port|Capacity: 1\./);
});

test('editing technical Value fields preserves another matching measurement', () => {
	const previous = current({
		description: 'Component. Resistance Value: 100. Capacitance Value: 100.',
		custom_fields: { 'Resistance Value': '100', 'Capacitance Value': '100' },
	});
	const changes = reconcileDescriptionMetadata(previous, {
		custom_fields: { 'Resistance Value': '200', 'Capacitance Value': '100' },
	});
	assert.match(changes.description, /Resistance Value: 200\./);
	assert.match(changes.description, /Capacitance Value: 100\./);
	assert.doesNotMatch(changes.description, /Capacitance Value: 200\./);
});

test('slash suffix does not suppress distinct part number', () => {
	const previous = current({ description: 'Version ABC-123/4.', model_number: null });
	const changes = reconcileDescriptionMetadata(previous, { model_number: 'ABC-123' });
	assert.match(changes.description, /Part\/model number: ABC-123\./);
});

test('short manufacturer names are corrected as complete tokens', () => {
	const previous = current({ description: 'GE appliances.', manufacturer: 'GE' });
	const changes = reconcileDescriptionMetadata(previous, { manufacturer: 'LG' });
	assert.match(changes.description, /LG appliances/);
	assert.doesNotMatch(changes.description, /GE appliances/);
});

test('technical Activation Voltage remains synchronized and VAT Reference is excluded', () => {
	const previous = current({
		description: 'Controller. Activation Voltage: 5V.',
		custom_fields: { 'Activation Voltage': '5V', 'VAT Reference': 'VAT-12' },
	});
	const changes = reconcileDescriptionMetadata(previous, {
		custom_fields: { 'Activation Voltage': '12V', 'VAT Reference': 'VAT-34' },
	});
	assert.match(changes.description, /Activation Voltage: 12V\./);
	assert.doesNotMatch(changes.description, /Activation Voltage: 5V|VAT-34/);
});

test('editing shorter label does not erase an overlapping longer label', () => {
	const previous = current({
		description: 'Controller. Activation Voltage: 5V. Voltage: 5V.',
		custom_fields: { 'Activation Voltage': '5V', Voltage: '5V' },
	});
	const updates = reconcileDescriptionMetadata(previous, {
		custom_fields: { 'Activation Voltage': '5V', Voltage: '12V' },
	});
	assert.match(updates.description, /Activation Voltage: 5V\./);
	assert.match(updates.description, /Voltage: 12V\./);
	assert.equal(updates.description, 'Controller. Activation Voltage: 5V. Voltage: 12V.');
});

test('clearing identity metadata retains prose without deleting its identifiers', () => {
	const previous = current({
		description:
			'WrongCo brackets, model OLD-123. Manufacturer: WrongCo. Part/model number: OLD-123.',
		manufacturer: 'WrongCo',
		model_number: 'OLD-123',
	});
	const updates = reconcileDescriptionMetadata(previous, {
		manufacturer: null,
		model_number: null,
	});
	assert.match(updates.description, /WrongCo brackets, model OLD-123\./);
	assert.doesNotMatch(updates.description, /Manufacturer: WrongCo\.|Part\/model number: OLD-123\./);
});

test('custom metadata names must match complete field-name terms', () => {
	const previous = current({ description: 'Electronic device.', custom_fields: {} });
	const updates = reconcileDescriptionMetadata(previous, {
		custom_fields: {
			'Storage Preferences': 'User layout',
			'Concurrent Users': '4',
			'Current Rating': '12A',
		},
	});
	assert.match(updates.description, /Current Rating: 12A\./);
	assert.doesNotMatch(updates.description, /Storage Preferences|Concurrent Users/);
});

test('an unrelated number in prose cannot suppress a labelled custom field', () => {
	const previous = current({ description: 'Converter with 2 ports', custom_fields: {} });
	const updates = reconcileDescriptionMetadata(previous, { custom_fields: { Capacity: '2' } });
	assert.equal(updates.description, 'Converter with 2 ports. Capacity: 2.');
});

test('a manufacturer correction preserves the entire note after the last metadata heading', () => {
	for (const note of [
		'Safety: WrongCo solvent is hazardous.',
		'Safety: RightCo solvent is hazardous.',
	]) {
		const previous = current({
			description: 'Relay. Manufacturer: WrongCo. ' + note,
			manufacturer: 'WrongCo',
		});
		const updates = reconcileDescriptionMetadata(previous, { manufacturer: 'RightCo' });
		assert.equal(updates.description, 'Relay. Manufacturer: RightCo. ' + note);
	}
});

test('a bulk clear and replacement keep the original boundary for every field', () => {
	const previous = current({
		description: 'Relay. Manufacturer: WrongCo. Safety: OLD-123 is hazardous.',
		manufacturer: 'WrongCo',
		model_number: 'OLD-123',
	});
	const updates = reconcileDescriptionMetadata(previous, {
		manufacturer: null,
		model_number: 'NEW-456',
	});
	assert.equal(
		updates.description,
		'Relay. Safety: OLD-123 is hazardous. Part/model number: NEW-456.'
	);
});

test('re-rendering all fields does not replace an identifier inserted by a different edit', () => {
	let item = current({
		description: 'ACME module, model SONY.',
		manufacturer: 'ACME',
		model_number: 'SONY',
	});
	item = { ...item, ...reconcileDescriptionMetadata(item, { manufacturer: 'SONY' }) };
	item = { ...item, ...reconcileDescriptionMetadata(item, { model_number: 'ABC-123' }) };
	assert.equal(item.description, 'SONY module, model ABC-123.');
});

test('returning every field to its starting value restores the original narrative and notes', () => {
	const original = 'Relay. Manufacturer: WrongCo. Safety: OLD-123 is hazardous.';
	let item = current({ description: original, manufacturer: 'WrongCo', model_number: 'OLD-123' });
	for (const fields of [
		{ manufacturer: '' },
		{ model_number: 'NEW-456' },
		{ manufacturer: 'WrongCo' },
		{ model_number: 'OLD-123' },
	]) {
		item = { ...item, ...reconcileDescriptionMetadata(item, fields) };
	}
	assert.equal(item.description, original);
});

test('authored compatibility headings do not become the primary manufacturer', () => {
	const item = current({
		description: 'Adapter. Compatible Manufacturer: Acme.',
		manufacturer: 'Acme',
	});
	const update = reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' });
	assert.equal(update.description, 'Adapter. Compatible Manufacturer: Acme. Manufacturer: NewCo.');
});

test('an automatically appended identity has a standalone heading on later saves', () => {
	let item = current({ description: 'Unpunctuated prose', model_number: null });
	item = { ...item, ...reconcileDescriptionMetadata(item, { model_number: 'OLD-123' }) };
	assert.equal(item.description, 'Unpunctuated prose. Part/model number: OLD-123.');
});

test('numeric regulator models change without rewriting matching quantities or ratings', () => {
	const item = current({
		name: 'Voltage regulator',
		model_number: '7805',
		description: 'A 7805 voltage regulator. Stock count 7805, measured at 7805 mV.',
	});
	const update = reconcileDescriptionMetadata(item, { model_number: '7905' });
	assert.equal(
		update.description,
		'A 7905 voltage regulator. Stock count 7805, measured at 7805 mV.'
	);
});

test('short numeric identities need a cue specific to their field', () => {
	const item = current({
		model_number: '12',
		serial_number: '34',
		description: '12 ports, model 12, serial 34, 34 spares.',
	});
	const update = reconcileDescriptionMetadata(item, { model_number: '45', serial_number: '67' });
	assert.equal(update.description, '12 ports, model 45, serial 67, 34 spares.');
});

test('unpunctuated technical headings can be changed and cleared without touching later lines', () => {
	for (const note of ['', '\nKeep dry.', '\r\nKeep dry.']) {
		const original = current({
			description: 'Controller. Voltage: 12V' + note,
			custom_fields: { Voltage: '12V' },
		});
		const changed = reconcileDescriptionMetadata(original, { custom_fields: { Voltage: '24V' } });
		assert.equal(changed.description, 'Controller. Voltage: 24V' + note);
		const cleared = reconcileDescriptionMetadata(
			{ ...original, ...changed },
			{ custom_fields: {} }
		);
		assert.equal(cleared.description, 'Controller.' + note);
	}
});

test('a newly excluded currency value cannot leave the old technical rating behind', () => {
	const item = current({
		description: 'Controller. Voltage: 12V.',
		custom_fields: { Voltage: '12V' },
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { custom_fields: { Voltage: '£24' } }).description,
		'Controller.'
	);
});

test('correcting a currency-prefixed technical value replaces just its old labelled clause', () => {
	const item = current({
		description: 'Controller. Voltage: £24. Note: receipt says £24.',
		custom_fields: { Voltage: '£24' },
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { custom_fields: { Voltage: '24V' } }).description,
		'Controller. Voltage: 24V. Note: receipt says £24.'
	);
	assert.equal(
		reconcileDescriptionMetadata(item, { custom_fields: { Voltage: '€20' } }).description,
		'Controller. Note: receipt says £24.'
	);
});

test('a manufacturer ending in a full stop can share the sentence delimiter with later notes', () => {
	const item = current({
		description: 'Relay. Manufacturer: Acme Inc. Part/model number: P-1. Keep dry.',
		manufacturer: 'Acme Inc.',
	});
	for (const [manufacturer, clause] of [
		['NewCo', ' Manufacturer: NewCo.'],
		['NewCo Ltd.', ' Manufacturer: NewCo Ltd.'],
		['Yahoo!', ' Manufacturer: Yahoo!'],
		['', ''],
	]) {
		const changed = reconcileDescriptionMetadata(item, { manufacturer });
		assert.equal(changed.description, 'Relay.' + clause + ' Part/model number: P-1. Keep dry.');
	}
	const blank = current({ description: 'Relay.', manufacturer: null });
	assert.equal(
		reconcileDescriptionMetadata(blank, { manufacturer: 'Acme Inc.' }).description,
		'Relay. Manufacturer: Acme Inc.'
	);
});

test('spaces or tabs before a label colon do not retain the wrong rating or manufacturer', () => {
	for (const gap of [' ', '\t']) {
		const item = current({
			description: 'Controller. Voltage' + gap + ': 12V. Manufacturer' + gap + ': Acme. Keep dry.',
			custom_fields: { Voltage: '12V' },
			manufacturer: 'Acme',
		});
		const update = reconcileDescriptionMetadata(item, {
			custom_fields: { Voltage: '24V' },
			manufacturer: 'NewCo',
		});
		assert.equal(update.description, 'Controller. Voltage: 24V. Manufacturer: NewCo. Keep dry.');
		const cleared = reconcileDescriptionMetadata(item, { custom_fields: {}, manufacturer: '' });
		assert.equal(cleared.description, 'Controller. Keep dry.');
	}
});

test('a qualified name and its note stay together when the current manufacturer changes', () => {
	for (const name of ['Acme', 'Acme Inc.', 'St. Jude']) {
		for (const note of ['(UK).', '[recalled; do not energize].']) {
			const item = current({
				description: 'Relay. Manufacturer: ' + name + ' ' + note,
				manufacturer: name,
			});
			const old = 'Relay. Previous manufacturer: ' + name + ' ' + note;
			assert.equal(
				reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' }).description,
				old + ' Manufacturer: NewCo.'
			);
			assert.equal(reconcileDescriptionMetadata(item, { manufacturer: '' }).description, old);
		}
	}
});

test('a technical rating can be corrected or cleared without losing its annotation', () => {
	const item = current({
		description: 'Controller. Voltage: 12V (DC). Keep dry.',
		custom_fields: { Voltage: '12V' },
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { custom_fields: { Voltage: '24V' } }).description,
		'Controller. Voltage: 24V (DC). Keep dry.'
	);
	assert.equal(
		reconcileDescriptionMetadata(item, { custom_fields: {} }).description,
		'Controller. Previous voltage: 12V (DC). Keep dry.'
	);
});

test('short model and serial codes change only after the corresponding identity cue', () => {
	const item = current({
		description: 'Sony mirrorless camera, model A7, serial A7, stored on shelf A7 near A9.',
		model_number: 'A7',
		serial_number: 'A7',
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { model_number: 'A9', serial_number: 'B2' }).description,
		'Sony mirrorless camera, model A9, serial B2, stored on shelf A7 near A9.'
	);
	const shelf = current({ description: 'Camera stored on shelf A9.', model_number: null });
	assert.equal(
		reconcileDescriptionMetadata(shelf, { model_number: 'A9' }).description,
		'Camera stored on shelf A9. Part/model number: A9.'
	);
});

test('explicit field wording takes priority when manufacturer, model and serial share a long code', () => {
	const item = current({
		description: 'Device by brand ABC-123, model ABC-123, serial ABC-123. See ABC-123 for details.',
		manufacturer: 'ABC-123',
		model_number: 'ABC-123',
		serial_number: 'ABC-123',
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { model_number: 'DEF-456' }).description,
		'Device by brand ABC-123, model DEF-456, serial ABC-123. See ABC-123 for details.'
	);
	assert.equal(
		reconcileDescriptionMetadata(item, {
			manufacturer: 'NewCo',
			model_number: 'DEF-456',
			serial_number: 'XYZ-789',
		}).description,
		'Device by brand NewCo, model DEF-456, serial XYZ-789. See ABC-123 for details.'
	);
	const other = current({ description: 'Device, serial ABC-123.', model_number: null });
	assert.equal(
		reconcileDescriptionMetadata(other, { model_number: 'ABC-123' }).description,
		'Device, serial ABC-123. Part/model number: ABC-123.'
	);
});

test('field wording on a previous line cannot claim a shared brand and model', () => {
	for (const newline of ['\n', '\r\n']) {
		const original = 'Spare part' + newline + 'ACME relay.';
		const item = current({ description: original, manufacturer: 'ACME', model_number: 'ACME' });
		assert.equal(
			reconcileDescriptionMetadata(item, { model_number: 'OTHER' }).description,
			original + ' Part/model number: OTHER.'
		);
	}
});

test('colon-bearing model and serial cues are editable before protected authored headings', () => {
	const item = current({
		description: 'Device, model: ABC-123, serial: ABC-123. Safety: model: ABC-123 is recalled.',
		model_number: 'ABC-123',
		serial_number: 'ABC-123',
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { model_number: 'DEF-456', serial_number: 'XYZ-789' })
			.description,
		'Device, model: DEF-456, serial: XYZ-789. Safety: model: ABC-123 is recalled.'
	);
	const previous = current({ description: 'Previous model: ABC-123.', model_number: 'ABC-123' });
	assert.equal(
		reconcileDescriptionMetadata(previous, { model_number: 'DEF-456' }).description,
		'Previous model: ABC-123. Part/model number: DEF-456.'
	);
});

test('a photo or an unrelated field edit after renaming cannot restore the original numeric model', () => {
	let item = current({
		name: 'Relay',
		description: 'A 123 relay.',
		model_number: '123',
		custom_fields: { Colour: 'red' },
	});
	item = { ...item, ...reconcileDescriptionMetadata(item, { model_number: '456' }) };
	item = { ...item, ...reconcileDescriptionMetadata(item, { name: 'Pump' }) };
	const photo = reconcileDescriptionMetadata(item, {
		...item,
		custom_fields: { ...item.custom_fields },
		customThumbnail: 'photo',
	});
	assert.equal(photo.description, 'A 456 relay.');
	assert.equal(photo.descriptionSource, item.descriptionSource);
	assert.equal(
		reconcileDescriptionMetadata({ ...item, ...photo }, { manufacturer: 'Maker' }).description,
		'A 456 relay. Manufacturer: Maker.'
	);
});

test('nonbreaking and other horizontal spaces preserve field ownership and the authored spacing', () => {
	for (const gap of ['\u00a0', '\u202f', '\u3000', '\t']) {
		const text = 'Device, serial' + gap + 'number:' + gap + 'ABC-123.';
		const item = current({ description: text, model_number: 'ABC-123', serial_number: 'ABC-123' });
		assert.equal(
			reconcileDescriptionMetadata(item, { model_number: 'DEF-456' }).description,
			text + ' Part/model number: DEF-456.'
		);
	}
});

test('a product-prefixed model cue is editable but a comma-delimited warning stays intact', () => {
	const item = current({
		description: 'Cordless drill model: ABC-123, Warning: model: ABC-123 is recalled.',
		model_number: 'ABC-123',
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { model_number: 'DEF-456' }).description,
		'Cordless drill model: DEF-456, Warning: model: ABC-123 is recalled.'
	);
});

test('comma-separated prose can correct both model and serial and retain a warning', () => {
	const item = current({
		description: 'Device, serial number: SN-123, model ABC-456, Warning: avoid SN-123.',
		serial_number: 'SN-123',
		model_number: 'ABC-456',
	});
	assert.equal(
		reconcileDescriptionMetadata(item, { serial_number: 'SN-234', model_number: 'ABC-789' })
			.description,
		'Device, serial number: SN-234, model ABC-789, Warning: avoid SN-123.'
	);
	const heading = current({ description: 'Manufacturer: Acme, keep dry.', manufacturer: 'Acme' });
	assert.equal(
		reconcileDescriptionMetadata(heading, { manufacturer: 'NewCo Inc.' }).description,
		'Manufacturer: NewCo Inc., keep dry.'
	);
});

test('an identity correction cannot change which appliances the item fits', () => {
	for (const [prose, expected] of [
		['Compatible with Acme appliances.', 'Compatible with Acme appliances. Manufacturer: NewCo.'],
		[
			'Acme adapter. Compatible with Acme appliances.',
			'NewCo adapter. Compatible with Acme appliances.',
		],
		[
			'Compatible with NewCo and Acme appliances.',
			'Compatible with NewCo and Acme appliances. Manufacturer: NewCo.',
		],
		[
			'Compatible with Acme appliances, manufactured by Acme.',
			'Compatible with Acme appliances, manufactured by NewCo.',
		],
	]) {
		const item = current({ description: prose, manufacturer: 'Acme' });
		assert.equal(
			reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' }).description,
			expected
		);
	}
});

test('Unicode spacing before a note remains intact after an identity correction', () => {
	for (const gap of ['\u00a0', '\u202f', '\u3000']) {
		const item = current({
			description: 'Relay. Manufacturer: Acme' + gap + '(recalled).',
			manufacturer: 'Acme',
		});
		assert.equal(
			reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' }).description,
			'Relay. Previous manufacturer: Acme' + gap + '(recalled). Manufacturer: NewCo.'
		);
	}
});

test('decimal sizes and abbreviations do not end a compatibility statement', () => {
	for (const detail of ['3.5 mm', 'approx. 3.5 mm', 'rev. 2', 'e.g.', 'St. Jude']) {
		const fit = 'Fits ' + detail + ' Acme sockets.';
		const item = current({
			description: 'Acme adapter. ' + fit + ' Acme cable included.',
			manufacturer: 'Acme',
		});
		assert.equal(
			reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' }).description,
			'NewCo adapter. ' + fit + ' NewCo cable included.'
		);
	}
});

test('metadata on Unicode-separated lines can be changed and cleared without swallowing the note', () => {
	for (const separator of ['\u2028', '\u2029', '\r', '\u0085']) {
		const item = current({
			description: 'Relay' + separator + 'Manufacturer: Acme' + separator + 'Keep dry.',
			manufacturer: 'Acme',
		});
		assert.equal(
			reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' }).description,
			'Relay' + separator + 'Manufacturer: NewCo' + separator + 'Keep dry.'
		);
		assert.equal(
			reconcileDescriptionMetadata(item, { manufacturer: '' }).description,
			'Relay' + separator + 'Keep dry.'
		);
	}
});

test('comma-separated technical ratings replace or clear the actual field and any legacy duplicate', () => {
	for (const duplicate of ['', ' Current: 2A.']) {
		const item = current({
			description: 'Controller. Voltage: 12V, Current: 2A.' + duplicate,
			custom_fields: { Voltage: '12V', Current: '2A' },
		});
		assert.equal(
			reconcileDescriptionMetadata(item, { custom_fields: { Voltage: '12V', Current: '3A' } })
				.description,
			'Controller. Voltage: 12V, Current: 3A.'
		);
		assert.equal(
			reconcileDescriptionMetadata(item, { custom_fields: { Voltage: '12V' } }).description,
			'Controller. Voltage: 12V.'
		);
	}
	const first = current({
		description: 'Controller, Current: 2A.',
		custom_fields: { Current: '2A' },
	});
	assert.equal(
		reconcileDescriptionMetadata(first, { custom_fields: {} }).description,
		'Controller.'
	);
});

test('the maker in an adapter description changes independently of a target introduced by for', () => {
	for (const [description, expected] of [
		['Acme adapter for Acme sockets.', 'NewCo adapter for Acme sockets.'],
		['Adapter for Acme sockets.', 'Adapter for Acme sockets. Manufacturer: NewCo.'],
		[
			'Adapter for NewCo sockets, manufactured by Acme.',
			'Adapter for NewCo sockets, manufactured by NewCo.',
		],
	]) {
		const item = current({ description, manufacturer: 'Acme' });
		assert.equal(
			reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' }).description,
			expected
		);
	}
});

test('changing model or serial protects repeated identifiers referenced as compatibility targets', () => {
	for (const [field, label] of [
		['model_number', 'Part/model number'],
		['serial_number', 'Serial number'],
	]) {
		const input = { [field]: 'ABC-123' };
		const first = current({ ...input, description: 'ABC-123 adapter for ABC-123 sockets.' });
		assert.equal(
			reconcileDescriptionMetadata(first, { [field]: 'DEF-456' }).description,
			'DEF-456 adapter for ABC-123 sockets.'
		);
		const target = current({ ...input, description: 'Adapter for ABC-123 and DEF-456 sockets.' });
		assert.equal(
			reconcileDescriptionMetadata(target, { [field]: 'DEF-456' }).description,
			'Adapter for ABC-123 and DEF-456 sockets. ' + label + ': DEF-456.'
		);
	}
});

test('an explicit maker after a fitment target is independent of punctuation', () => {
	for (const cue of ['made by', 'manufactured by']) {
		const item = current({
			description: 'Adapter for OldCo sockets ' + cue + ' OldCo.',
			manufacturer: 'OldCo',
		});
		assert.equal(
			reconcileDescriptionMetadata(item, { manufacturer: 'NewCo' }).description,
			'Adapter for OldCo sockets ' + cue + ' NewCo.'
		);
	}
});

test('identity edits preserve uncued measurements and ordinary words', () => {
	const supply = current({
		description: '12V DC power supply, model 12V.',
		model_number: '12V',
	});
	assert.equal(
		reconcileDescriptionMetadata(supply, { model_number: 'LRS-100-12' }).description,
		'12V DC power supply, model LRS-100-12.'
	);
	const controller = current({
		description: 'Controller with power switched on.',
		manufacturer: 'ON',
	});
	assert.equal(
		reconcileDescriptionMetadata(controller, { manufacturer: 'ST' }).description,
		'Controller with power switched on. Manufacturer: ST.'
	);
	const replacement = current({
		description: '24V DC power supply, model 12V.',
		model_number: '12V',
	});
	assert.equal(
		reconcileDescriptionMetadata(replacement, { model_number: '24V' }).description,
		'24V DC power supply, model 24V.'
	);
});
