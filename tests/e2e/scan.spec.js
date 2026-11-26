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
  await expect(page.getByRole('heading', { name: 'Ok', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Ok', exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Naskenovat další formulář' }).click();
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
});

test('failed scan remains on home and the same photo can be selected again', async ({ page, scanApi }) => {
  scanApi.respond = async (request, response) => {
    if (scanApi.requests.length === 1) {
      response.writeHead(500).end(JSON.stringify({ detail: 'Form processing failed' }));
    } else {
      await forwardScan(request, response);
    }
  };
  await page.goto('/');
  await takePhoto(page);
  await expect(page.getByRole('alert')).toContainText('Formulář se nepodařilo zpracovat');
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
  await takePhoto(page);
  await expect(page.getByRole('heading', { name: 'Ok', exact: true })).toBeVisible();
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
  await expect(page.getByRole('heading', { name: 'Ok', exact: true })).toBeVisible();
  const upload = scanApi.requests[0];
  expect(upload.headers['content-type']).toBe('image/jpeg');
  expect([...upload.body.subarray(0, 2)]).toEqual([0xff, 0xd8]);
  expect([...upload.body.subarray(-2)]).toEqual([0xff, 0xd9]);
});

test('server upload limits show an understandable error', async ({ page, scanApi }) => {
  scanApi.respond = async (_request, response) => {
    response.writeHead(422).end(JSON.stringify({ detail: 'Image must not exceed 100 bytes' }));
  };
  await page.goto('/');
  await takePhoto(page);
  await expect(page.getByRole('alert')).toContainText('Fotka je příliš velká');
  await expect(page.getByRole('button', { name: 'Vyfotit formulář' })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Ok', exact: true })).not.toBeVisible();
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
  await expect(page.getByRole('heading', { name: 'Ok', exact: true })).toBeVisible();
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
