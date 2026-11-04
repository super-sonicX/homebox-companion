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
