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
