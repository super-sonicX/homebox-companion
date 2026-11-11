import { test, expect } from '@playwright/test';

test('chat lists Homebox locations through LiteLLM function tools', async ({ page }) => {
	const initialized = page.waitForResponse(
		(response) =>
			new URL(response.url()).pathname === '/api/chat/pending' &&
			response.request().method() === 'GET'
	);
	await page.goto('/chat');
	expect((await initialized).ok()).toBe(true);

	await page.getByLabel('Chat message input').fill('List my storage locations');
	const streaming = page.waitForResponse(
		(response) =>
			new URL(response.url()).pathname === '/api/chat/messages' &&
			response.request().method() === 'POST'
	);
	await page.getByRole('button', { name: 'Send message' }).click();

	const response = await streaming;
	expect(response.ok()).toBe(true);
	expect(await response.finished()).toBeNull();
	const events = await response.text();
	expect(events).toMatch(/^event: done\r?$/m);
	expect(events).not.toMatch(/^event: error\r?$/m);
	await expect(page.getByLabel('Chat message input')).toBeVisible();
	await expect(page.locator('.chat-bubble').last()).toContainText(
		'Your inventory includes Smoke storage.',
		{ timeout: 15_000 }
	);
	await expect(page.getByText('The LLM provider stream failed. Please try again.')).toHaveCount(0);
});
