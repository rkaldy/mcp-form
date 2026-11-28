import assert from 'node:assert/strict';
import test from 'node:test';
import { readScanStream } from '../../../ui/src/api.js';

function response(chunks) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  }));
}

const encode = (value) => new TextEncoder().encode(value);

async function events(response) {
  const messages = [];
  for await (const message of readScanStream(response)) messages.push(message);
  return messages;
}

test('NDJSON survives split lines, UTF-8 characters and a final line without newline', async () => {
  const progress = { session_id: null, status: 'normalizing', reviews: [] };
  const error = { error: 'Chyba při čtení', error_details: 'Nečitelný formulář', fatal: false };
  const bytes = encode(`${JSON.stringify(progress)}\r\n\n${JSON.stringify(error)}`);
  const chunks = Array.from(bytes, (byte) => new Uint8Array([byte]));
  assert.deepEqual(await events(response(chunks)), [progress, error]);
});

test('progress is available before the next network chunk arrives', async () => {
  let controller;
  const body = new ReadableStream({ start(stream) { controller = stream; } });
  const stream = readScanStream(new Response(body));
  const progress = { status: 'processing', session_id: 'test-session', reviews: [] };
  controller.enqueue(encode(`${JSON.stringify(progress)}\n`));
  assert.deepEqual((await stream.next()).value, progress);
  const finished = { ...progress, status: 'finished' };
  controller.enqueue(encode(`${JSON.stringify(finished)}\n`));
  controller.close();
  assert.deepEqual((await stream.next()).value, finished);
  assert.equal((await stream.next()).done, true);
});

test('a closed stream without a final result cannot imply success', async () => {
  await assert.rejects(events(response([encode('{"status":"processing"}\n')])), /before a result/);
});

test('malformed JSON and unknown messages are rejected', async () => {
  await assert.rejects(events(response([encode('{broken}\n')])));
  await assert.rejects(events(response([encode('{"status":"unknown"}\n')])), /Invalid scan response/);
  await assert.rejects(events(response([encode('{"status":"reviewing"}\n')])), /Invalid review response/);
});

test('a terminal error cancels the remaining response instead of emitting later success', async () => {
  const error = { error: 'Chyba', error_details: '', fatal: true };
  assert.deepEqual(await events(response([
    encode(`${JSON.stringify(error)}\n{"status":"finished"}\n`),
  ])), [error]);
});
