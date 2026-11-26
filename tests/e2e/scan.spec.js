import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { expect, test as base } from '@playwright/test';

const imagePath = fileURLToPath(new URL('./fixtures/blank.jpg', import.meta.url));

async function forwardScan(upload, response) {
  const result = await fetch('http://127.0.0.1:4173/api/scan', {
    method: upload.method,
    headers: { 'Content-Type': 'image/jpeg' },
    body: upload.body,
  });
  response.writeHead(result.status).end(Buffer.from(await result.arrayBuffer()));
}

// Receive uploads over HTTP: WebKit's request inspector does not expose File bodies.
const test = base.extend({
  scanApi: async ({ page }, use) => {
    const api = {
      requests: [],
      respond: forwardScan,
    };
    const server = createServer(async (request, response) => {
      response.setHeader('Access-Control-Allow-Origin', '*');
      response.setHeader('Access-Control-Allow-Headers', 'Content-Type');
      response.setHeader('Content-Type', 'application/json');
      if (request.method === 'OPTIONS') {
        response.writeHead(204).end();
        return;
      }
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const upload = { method: request.method, headers: request.headers, body: Buffer.concat(chunks) };
      api.requests.push(upload);
      await api.respond(upload, response);
    });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const url = `http://127.0.0.1:${server.address().port}/api/scan`;
    await page.route('**/api/scan', (route) => route.continue({ url }));
    try {
      await use(api);
    } finally {
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    }
  },
});

async function takePhoto(page, file = imagePath) {
  await page.evaluate(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      value: async () => { throw new DOMException('Camera denied for upload test', 'NotAllowedError'); },
    });
  });
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Vyfotit formulář' }).click();
  await page.getByRole('button', { name: 'Vybrat fotografii' }).click();
  await (await chooser).setFiles(file);
}

test('home has no horizontal overflow and the empty menu opens and closes', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Form Scanner — úvodní stránka' })).toBeVisible();
  const capture = page.getByLabel('Fotografie formuláře');
  await expect(capture).toHaveAttribute('accept', 'image/*');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole('button', { name: 'Otevřít menu' }).click();
  const menu = page.getByRole('dialog', { name: 'Menu' });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole('navigation')).toBeEmpty();
  await page.keyboard.press('Escape');
  await expect(menu).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Otevřít menu' })).toBeFocused();
  await page.getByRole('button', { name: 'Otevřít menu' }).click();
  await page.getByRole('button', { name: 'Zavřít menu' }).click();
  await expect(menu).not.toBeVisible();
});

test('camera upload sends exact JPEG bytes and shows pending and success states', async ({ page, scanApi }) => {
  const image = await readFile(imagePath);
  let complete;
  const waiting = new Promise((resolve) => { complete = resolve; });
  scanApi.respond = async (request, response) => {
    await waiting;
    await forwardScan(request, response);
  };
  await page.goto('/');
  await takePhoto(page);
  await expect(page.getByRole('button', { name: 'Čteme formulář…' })).toBeDisabled();
  await expect(page.getByRole('status')).toContainText('Čteme formulář…');
  await expect.poll(() => scanApi.requests.length).toBe(1);
  const upload = scanApi.requests[0];
  expect(upload.method).toBe('POST');
  expect(upload.headers['content-type']).toBe('image/jpeg');
  expect(upload.body).toEqual(image);
  complete();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.', exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Naskenovat další formulář' }).click();
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
});

test('failed scan remains on home and the same photo can be selected again', async ({ page, scanApi }) => {
  scanApi.respond = async (request, response) => {
    if (scanApi.requests.length === 1) {
      response.writeHead(500).end(JSON.stringify({ error: 'Zpracování selhalo', details: 'Testovací chyba serveru' }));
    } else {
      await forwardScan(request, response);
    }
  };
  await page.goto('/');
  await takePhoto(page);
  await expect(page.getByRole('alert')).toContainText('Zpracování selhalo');
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
  await takePhoto(page);
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.', exact: true })).toBeVisible();
  expect(scanApi.requests).toHaveLength(2);
});

test('non-JPEG camera images are converted to the JPEG accepted by the API', async ({ page, scanApi }) => {
  await page.goto('/');
  const png = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 16;
    canvas.height = 16;
    const context = canvas.getContext('2d');
    context.fillStyle = '#496951';
    context.fillRect(0, 0, 16, 16);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await takePhoto(page, { name: 'photo.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') });
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.', exact: true })).toBeVisible();
  const upload = scanApi.requests[0];
  expect(upload.headers['content-type']).toBe('image/jpeg');
  expect([...upload.body.subarray(0, 2)]).toEqual([0xff, 0xd8]);
  expect([...upload.body.subarray(-2)]).toEqual([0xff, 0xd9]);
});

test('server upload limits show an understandable error', async ({ page, scanApi }) => {
  scanApi.respond = async (_request, response) => {
    response.writeHead(422).end(JSON.stringify({ error: 'Obrázek je příliš velký', details: 'Maximální velikost je 100 bajtů.' }));
  };
  await page.goto('/');
  await takePhoto(page);
  await expect(page.getByRole('alert')).toContainText('Obrázek je příliš velký');
  await expect(page.getByRole('alert')).toContainText('Maximální velikost je 100 bajtů.');
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.', exact: true })).not.toBeVisible();
});

async function provideCamera(page, delayed = false) {
  await page.addInitScript(({ delayed }) => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      value: async (constraints) => {
        window.cameraConstraints = constraints;
        const canvas = document.createElement('canvas');
        canvas.width = 640;
        canvas.height = 480;
        const context = canvas.getContext('2d');
        context.fillStyle = '#d5b99a';
        context.fillRect(0, 0, 640, 480);
        const stream = canvas.captureStream(15);
        window.cameraTracks = stream.getTracks();
        const repaint = setInterval(() => context.fillRect(0, 0, 640, 480), 50);
        for (const track of stream.getTracks()) {
          const stop = track.stop.bind(track);
          track.stop = () => { clearInterval(repaint); stop(); };
        }
        if (delayed) await new Promise((resolve) => { window.allowCamera = resolve; });
        return stream;
      },
    });
  }, { delayed });
}

test('camera preview captures and uploads a JPEG, then stops all tracks', async ({ page, scanApi }) => {
  await provideCamera(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Vyfotit formulář' }).click();
  const camera = page.getByRole('dialog', { name: 'Vyfotit formulář' });
  await expect(camera).toBeVisible();
  await expect(page.getByRole('button', { name: 'Vyfotit', exact: true })).toBeEnabled();
  expect(await page.evaluate(() => window.cameraConstraints.audio)).toBe(false);
  expect(await page.evaluate(() => window.cameraConstraints.video.facingMode)).toEqual({ ideal: 'environment' });
  await page.getByRole('button', { name: 'Vyfotit', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.', exact: true })).toBeVisible();
  expect(scanApi.requests).toHaveLength(1);
  expect(scanApi.requests[0].headers['content-type']).toBe('image/jpeg');
  expect([...scanApi.requests[0].body.subarray(0, 2)]).toEqual([0xff, 0xd8]);
  await expect(camera).not.toBeVisible();
  expect(await page.evaluate(() => window.cameraTracks.every((track) => track.readyState === 'ended'))).toBe(true);
});

test('closing the camera stops the stream and does not upload a photo', async ({ page, scanApi }) => {
  await provideCamera(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Vyfotit formulář' }).click();
  await expect(page.getByRole('button', { name: 'Vyfotit', exact: true })).toBeEnabled();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Vyfotit formulář' })).not.toBeVisible();
  expect(await page.evaluate(() => window.cameraTracks.every((track) => track.readyState === 'ended'))).toBe(true);
  expect(scanApi.requests).toHaveLength(0);
});

test('late camera permission after closing the dialog does not leave the camera running', async ({ page, scanApi }) => {
  await provideCamera(page, true);
  await page.goto('/');
  await page.getByRole('button', { name: 'Vyfotit formulář' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Spouštíme kameru' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.evaluate(() => window.allowCamera());
  await expect.poll(() => page.evaluate(() => window.cameraTracks.every((track) => track.readyState === 'ended'))).toBe(true);
  await expect(page.getByRole('dialog', { name: 'Vyfotit formulář' })).not.toBeVisible();
  expect(scanApi.requests).toHaveLength(0);
});

test('camera permission denial explains the problem and allows file selection', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      value: async () => { throw new DOMException('Denied', 'NotAllowedError'); },
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Vyfotit formulář' }).click();
  await expect(page.getByRole('alert')).toContainText('Povolte prosím přístup ke kameře');
  await expect(page.getByRole('button', { name: 'Vybrat fotografii' })).toBeEnabled();
  await page.getByRole('button', { name: 'Zavřít kameru' }).click();
  await expect(page.getByRole('dialog', { name: 'Vyfotit formulář' })).not.toBeVisible();
});

const reviewImagePath = fileURLToPath(new URL('./fixtures/review.jpg', import.meta.url));

async function openReview(page) {
  await page.goto('/');
  await takePhoto(page, reviewImagePath);
  await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).toBeVisible();
}

async function fillCorrections(page) {
  await page.getByRole('textbox', { name: 'Název aktivity', exact: true }).fill('Opravená aktivita');
  await page.getByRole('textbox', { name: 'Datum realizace (od - do)', exact: true }).fill('9.11.2026');
  await page.getByRole('textbox', { name: 'Jméno a příjmení účastníka: Jméno', exact: true }).fill('Eva');
  await page.getByRole('textbox', { name: 'Jméno a příjmení účastníka: Příjmení', exact: true }).fill('Ukázková');
}

test('review loads real crops, validates corrections and confirms completed processing', async ({ page }) => {
  await openReview(page);
  await expect(page.getByRole('textbox', { name: 'Název aktivity', exact: true })).toHaveValue('Testovací aktivita');
  const date = page.getByRole('textbox', { name: 'Datum realizace (od - do)', exact: true });
  await expect(date).toHaveValue('8.11.2026');
  await expect(page.getByRole('img', { name: /^Výřez:/ })).toHaveCount(3);
  for (const crop of await page.getByRole('img', { name: /^Výřez:/ }).all()) {
    await expect.poll(() => crop.evaluate((image) => image.naturalWidth)).toBe(32);
    expect(await crop.evaluate((image) => image.naturalHeight)).toBe(24);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await fillCorrections(page);
  await date.fill('31.2.2026');
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByText('Zadejte platné datum ve formátu D.M.YYYY.', { exact: true })).toBeVisible();
  await expect(date).toBeFocused();
  // The native picker updates the editable Czech date representation too.
  await page.getByLabel('Vybrat datum: Datum realizace (od - do)', { exact: true }).fill('2026-11-09');
  await expect(date).toHaveValue('9.11.2026');
  let finish;
  const waiting = new Promise((resolve) => { finish = resolve; });
  await page.route('**/api/scan/review', async (route) => {
    await waiting;
    await route.continue();
  });
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Zpracováváme…', exact: true })).toBeDisabled();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.' })).not.toBeVisible();
  finish();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.' })).toBeFocused();
});

test('server validation failure preserves corrections and allows another submission', async ({ page }) => {
  await openReview(page);
  await fillCorrections(page);
  let attempts = 0;
  await page.route('**/api/scan/review', async (route) => {
    if (++attempts === 1) await route.fulfill({ status: 422, json: { error: 'Chybně zadaná hodnota', detail: 'Zadejte platné datum.' } });
    else await route.continue();
  });
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Chybně zadaná hodnota');
  await expect(page.getByRole('alert')).toContainText('Zadejte platné datum.');
  await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).toBeVisible();
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.' })).toBeVisible();
});

test('review handles integers, decimal commas, checkboxes, nulls and missing crops', async ({ page, scanApi }) => {
  scanApi.respond = async (_request, response) => response.writeHead(200).end(JSON.stringify({
    session_id: '00000000-0000-0000-0000-000000000001',
    reviews: [
      { type: 'Decimal', path: 'amount', label: 'Částka', value: '12.5', bounding_box: null },
      { type: 'bool', path: 'confirmed', label: 'Potvrzeno', value: false, bounding_box: null },
      { type: 'str', path: 'note', label: 'Poznámka', value: null, bounding_box: null },
      { type: 'int', path: 'count', label: 'Počet', value: 2, bounding_box: null },
    ],
  }));
  await openReview(page);
  await expect(page.getByRole('textbox', { name: 'Poznámka', exact: true })).toBeEmpty();
  await expect(page.getByText('Výřez není k dispozici.', { exact: true })).toHaveCount(4);
  const amount = page.getByRole('textbox', { name: 'Částka', exact: true });
  await expect(amount).toHaveValue('12.5');
  const count = page.getByRole('textbox', { name: 'Počet', exact: true });
  await expect(count).toHaveValue('2');
  await count.fill('3.5');
  await amount.fill('12,3,4');
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByText('Zadejte celé číslo.', { exact: true })).toBeVisible();
  await expect(page.getByText('Zadejte desetinné číslo s tečkou nebo čárkou.', { exact: true })).toBeVisible();
  await count.fill('3');
  await amount.fill('12,75');
  await page.getByRole('checkbox', { name: 'Potvrzeno', exact: true }).check();
  let submitted;
  await page.route('**/api/scan/review', async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 204 });
  });
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.' })).toBeVisible();
  expect(submitted.reviews).toEqual([
    { path: 'amount', value: '12.75' }, { path: 'confirmed', value: true }, { path: 'note', value: null }, { path: 'count', value: 3 },
  ]);
});

test('crop failures can be retried without losing edited values', async ({ page }) => {
  let first = true;
  await page.route('**/api/scan/field?*', async (route) => {
    if (first) {
      first = false;
      await route.fulfill({ status: 503 });
    } else await route.continue();
  });
  await openReview(page);
  await fillCorrections(page);
  await expect(page.getByText('Výřez se nepodařilo načíst.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Zkusit znovu', exact: true }).click();
  await expect(page.getByRole('img', { name: /^Výřez:/ })).toHaveCount(3);
  await expect(page.getByRole('textbox', { name: 'Název aktivity', exact: true })).toHaveValue('Opravená aktivita');
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.' })).toBeVisible();
});

test('processing failure returns home with server error and details', async ({ page }) => {
  await openReview(page);
  await fillCorrections(page);
  await page.route('**/api/scan/review', (route) => route.fulfill({ status: 500, json: { error: 'Zpracování selhalo', details: 'Cílová tabulka není dostupná.' } }));
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  const alert = page.getByRole('alert');
  await expect(alert.locator('.error-title')).toHaveText('Zpracování selhalo');
  await expect(alert.locator('.error-details')).toHaveText('Cílová tabulka není dostupná.');
  expect(await alert.locator('.error-details').evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeLessThan(
    await alert.locator('.error-title').evaluate((element) => parseFloat(getComputedStyle(element).fontSize)),
  );
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.' })).not.toBeVisible();
  await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Odeslat', exact: true })).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeFocused();
});

test('real review validation errors show server text and retain all corrections', async ({ page }) => {
  await openReview(page);
  await fillCorrections(page);
  let validationError;
  let first = true;
  await page.route('**/api/scan/review', async (route) => {
    if (first) {
      first = false;
      const body = route.request().postDataJSON();
      body.reviews.find((field) => field.path === 'static_fields.date').value = 'not a date';
      const response = await route.fetch({ postData: JSON.stringify(body) });
      validationError = await response.json();
      await route.fulfill({ response });
    } else await route.continue();
  });
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  const alert = page.getByRole('alert');
  await expect(alert.locator('.error-title')).toHaveText('Chybně zadaná hodnota');
  await expect(alert.locator('.error-details')).toHaveText(validationError.details ?? validationError.detail);
  await expect(page.getByRole('textbox', { name: 'Název aktivity', exact: true })).toHaveValue('Opravená aktivita');
  await expect(page.getByRole('textbox', { name: 'Datum realizace (od - do)', exact: true })).toHaveValue('9.11.2026');
  await expect(page.getByRole('textbox', { name: 'Jméno a příjmení účastníka: Příjmení', exact: true })).toHaveValue('Ukázková');
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Formulář byl úspěšně zpracován.', exact: true })).toBeVisible();
});

for (const status of [500, 422]) {
  test(`crop HTTP ${status} displays server error on the appropriate page`, async ({ page }) => {
    await page.route('**/api/scan/field?*', (route) => route.fulfill({
      status,
      json: { error: 'Výřez nelze načíst', details: 'Testovací podrobnosti chyby výřezu.' },
    }));
    await page.goto('/');
    await takePhoto(page, reviewImagePath);
    const alert = page.getByRole('alert');
    await expect(alert.locator('.error-title')).toHaveText('Výřez nelze načíst');
    await expect(alert.locator('.error-details')).toHaveText('Testovací podrobnosti chyby výřezu.');
    if (status === 500) {
      await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
      await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).not.toBeVisible();
    } else {
      await expect(page.getByRole('heading', { name: 'Zkontroluj tato pole' })).toBeVisible();
      await expect(page.getByRole('textbox', { name: 'Název aktivity', exact: true })).toHaveValue('Testovací aktivita');
      await expect(page.getByRole('button', { name: 'Odeslat', exact: true })).toBeEnabled();
    }
  });
}

test('a server failure without JSON returns home with a fallback error', async ({ page }) => {
  await openReview(page);
  await fillCorrections(page);
  await page.route('**/api/scan/review', (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: 'Internal Server Error' }));
  await page.getByRole('button', { name: 'Odeslat', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Formulář se nepodařilo zpracovat.');
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeFocused();
});
