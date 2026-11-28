import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { expect, test as base } from '@playwright/test';

const image = fileURLToPath(new URL('./fixtures/blank.jpg', import.meta.url));
const success = 'Formulář úspěšně zpracován';
const test = base.extend({
  scenario: ['success', { option: true }],
  paused: [false, { option: true }],
  page: async ({ page, scenario, paused }, use) => {
    const headers = {
      'x-test-id': randomUUID(),
      'x-test-scenario': scenario,
      'x-test-paused': String(paused),
    };
    await page.context().setExtraHTTPHeaders(headers);
    // Exercise the real file chooser as the fallback for denied camera access.
    await page.addInitScript(() => {
      Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
        configurable: true,
        value: async () => { throw new DOMException('Test camera denied', 'NotAllowedError'); },
      });
    });
    await page.goto('/');
    try {
      await use(page);
    } finally {
      await page.request.delete('/__test/scenario', {
        headers,
      });
    }
  },
});

async function takePhoto(page, file = image) {
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Vyfotit formulář' }).click();
  await page.getByRole('button', { name: 'Vybrat fotografii' }).click();
  await (await chooser).setFiles(file);
}

async function fillCorrections(page) {
  await page.getByRole('textbox', { name: 'Datum', exact: true }).fill('9.11.2026');
  await page.getByRole('textbox', { name: 'Jméno účastníka: Jméno', exact: true }).fill('Eva');
  await page.getByRole('textbox', { name: 'Jméno účastníka: Příjmení', exact: true }).fill('Ukázková');
}

async function expectReady(page) {
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).not.toBeVisible();
}

test.describe('progressive scan', () => {
  test.use({ paused: true });
  test('shows all statuses before processing completes and permits another photo', async ({ page }) => {
    for (let photo = 0; photo < 2; photo += 1) {
      await takePhoto(page);
      for (const [stage, label] of [
        ['normalize', 'Otáčím a ořezávám formulář'],
        ['scan', 'Skenuji textová pole'],
        ['process', 'Zpracovávám data'],
      ]) {
        await expect(page.getByRole('button', { name: label })).toBeDisabled();
        await expect(page.getByText(success, { exact: true })).not.toBeVisible();
        const response = await page.request.post(`/__test/release/${stage}`);
        expect(response.ok()).toBe(true);
      }
      await expect(page.getByText(success, { exact: true })).toBeVisible();
      await expectReady(page);
    }
  });
});


async function openReview(page) {
  await takePhoto(page);
  await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).toBeVisible();
}

test('home fits the viewport and the menu opens and closes', async ({ page }) => {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Otevřít menu' }).click();
  await expect(page.getByRole('dialog', { name: 'Menu' })).toBeVisible();
  await page.getByRole('button', { name: 'Zavřít menu' }).click();
  await expect(page.getByRole('dialog', { name: 'Menu' })).not.toBeVisible();
  await expectReady(page);
});

for (const scenario of ['scan-user-error', 'scan-fatal-error']) {
  test.describe(scenario, () => {
    test.use({ scenario });
    test('scan errors show the error and detail on home with capture enabled', async ({ page }) => {
      await takePhoto(page);
      const alert = page.getByRole('alert');
      await expect(alert.locator('.error-title')).toHaveText(
        scenario === 'scan-user-error' ? 'Fotografii nelze přečíst' : 'Skenování selhalo',
      );
      await expect(alert.locator('.error-details')).toHaveText(
        scenario === 'scan-user-error' ? 'Vyfoťte ji znovu.' : 'Služba je nedostupná.',
      );
      await expectReady(page);
      await expect(page.getByText(success, { exact: true })).not.toBeVisible();
    });
  });
}

test.describe('review', () => {
  test.use({ scenario: 'review' });

  test('loads field values and crops, sends corrections and confirms processing', async ({ page }) => {
    await openReview(page);
    await expect(page.getByRole('textbox', { name: 'Datum', exact: true })).toHaveValue('8.11.2026');
    await expect(page.getByRole('textbox', { name: 'Jméno účastníka: Jméno', exact: true })).toHaveValue('Jana');
    const crops = page.getByRole('img', { name: /^Výřez:/ });
    await expect(crops).toHaveCount(2);
    for (const crop of await crops.all()) {
      await expect.poll(() => crop.evaluate((image) => image.naturalWidth)).toBe(16);
      expect(await crop.evaluate((image) => image.naturalHeight)).toBe(16);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await fillCorrections(page);
    await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
    // The processing double rejects a request unless it received every corrected value.
    await expect(page.getByText(success, { exact: true })).toBeVisible();
    await expectReady(page);
  });

  test('invalid dates stay editable and are not sent for processing', async ({ page }) => {
    await openReview(page);
    const date = page.getByRole('textbox', { name: 'Datum', exact: true });
    await date.fill('31.2.2026');
    let submitted = false;
    page.on('request', (request) => { if (request.url().endsWith('/api/scan/review')) submitted = true; });
    await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
    await expect(page.getByText('Zadejte platné datum ve formátu D.M.YYYY.', { exact: true })).toBeVisible();
    await expect(date).toBeFocused();
    expect(submitted).toBe(false);
    await fillCorrections(page);
    await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
    await expect(page.getByText(success, { exact: true })).toBeVisible();
  });

  test('a truncated review stream returns home without claiming success', async ({ page }) => {
    await openReview(page);
    await fillCorrections(page);
    await page.route('**/api/scan/review', (route) => route.fulfill({
      contentType: 'application/x-ndjson',
      body: JSON.stringify({ session_id: null, status: 'processing', reviews: [] }) + '\n',
    }));
    await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Nelze ověřit, zda byl formulář zpracován.');
    await expectReady(page);
    await expect(page.getByText(success, { exact: true })).not.toBeVisible();
  });
});

test.describe('recoverable review error', () => {
  test.use({ scenario: 'review-user-error', paused: true });
  test('restores review after PROCESSING, retains corrections and permits retry', async ({ page }) => {
    for (const stage of ['normalize', 'scan']) await page.request.post(`/__test/release/${stage}`);
    await openReview(page);
    await fillCorrections(page);
    await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Zpracovávám data' })).toBeDisabled();
    await page.request.post('/__test/release/process');
    const alert = page.getByRole('alert');
    await expect(alert.locator('.error-title')).toHaveText('Chybně zadaná hodnota');
    await expect(alert.locator('.error-details')).toHaveText('Zkontrolujte datum.');
    await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Datum', exact: true })).toHaveValue('9.11.2026');
    await expect(page.getByRole('textbox', { name: 'Jméno účastníka: Jméno' })).toHaveValue('Eva');
    await expect(page.getByRole('textbox', { name: 'Jméno účastníka: Příjmení' })).toHaveValue('Ukázková');
    await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Zpracovávám data' })).toBeDisabled();
    await page.request.post('/__test/release/process');
    await expect(page.getByText(success, { exact: true })).toBeVisible();
    await expectReady(page);
  });
});

test.describe('fatal review error', () => {
  test.use({ scenario: 'review-fatal-error' });
  test('returns home with the error and detail and enables another photo', async ({ page }) => {
    await openReview(page);
    await fillCorrections(page);
    await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
    const alert = page.getByRole('alert');
    await expect(alert.locator('.error-title')).toHaveText('Zpracování selhalo');
    await expect(alert.locator('.error-details')).toHaveText('Tabulka je nedostupná.');
    expect(await alert.locator('.error-details').evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeLessThan(
      await alert.locator('.error-title').evaluate((element) => parseFloat(getComputedStyle(element).fontSize)),
    );
    await expectReady(page);
    await expect(page.getByText(success, { exact: true })).not.toBeVisible();
  });
});

test('a truncated scan stream returns home instead of reporting success', async ({ page }) => {
  await page.route('**/api/scan', (route) => route.fulfill({
    contentType: 'application/x-ndjson',
    body: '{"session_id":null,"status":"normalizing","reviews":[]}\n',
  }));
  await takePhoto(page);
  await expect(page.getByRole('alert')).toContainText('Fotku se nepodařilo odeslat nebo přečíst.');
  await expectReady(page);
  await expect(page.getByText(success, { exact: true })).not.toBeVisible();
});

test('an HTTP failure without JSON displays a fallback error', async ({ page }) => {
  await page.route('**/api/scan', (route) => route.fulfill({
    status: 500, contentType: 'text/plain', body: 'Internal Server Error',
  }));
  await takePhoto(page);
  await expect(page.getByRole('alert')).toContainText('Formulář se nepodařilo zpracovat.');
  await expectReady(page);
});


test('an empty upload shows the streamed validation error on home', async ({ page }) => {
  await takePhoto(page, { name: 'empty.jpg', mimeType: 'image/jpeg', buffer: Buffer.alloc(0) });
  await expect(page.getByRole('alert').locator('.error-title')).toHaveText('Image must not be empty');
  await expectReady(page);
  await expect(page.getByText(success, { exact: true })).not.toBeVisible();
});
