<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import ReviewPage from './ReviewPage.vue';
import ErrorMessage from './ErrorMessage.vue';
import { readApiError, readScanStream, streamError } from './api.js';

const scan = ref(null);

const status = ref('idle');
const error = ref(null);
const fileInput = ref(null);
const captureButton = ref(null);
const processed = ref(false);
const progress = ref('');
const progressLabel = computed(() => ({
  normalizing: 'Otáčím a ořezávám formulář',
  scanning: 'Skenuji textová pole',
  processing: 'Zpracovávám data',
}[progress.value] ?? 'Odesílám formulář'));
const menu = ref(null);
const menuOpen = ref(false);

const camera = ref(null);
const video = ref(null);
const cameraReady = ref(false);
const cameraCapturing = ref(false);
const cameraError = ref('');
let cameraStream = null;
let cameraRequest = 0;

function stopCamera() {
  cameraRequest += 1;
  cameraStream?.getTracks().forEach((track) => track.stop());
  cameraStream = null;
  if (video.value) video.value.srcObject = null;
  cameraReady.value = false;
  cameraCapturing.value = false;
}

function closeCamera() {
  stopCamera();
  if (camera.value?.open) camera.value.close();
}

function cameraClosed() {
  if (!camera.value?.open) stopCamera();
}

async function openCamera() {
  if (status.value !== 'idle' || camera.value.open) return;
  cameraError.value = '';
  cameraReady.value = false;
  camera.value.showModal();
  const request = ++cameraRequest;
  if (!navigator.mediaDevices?.getUserMedia) {
    cameraError.value = window.isSecureContext
      ? 'Tento prohlížeč nepodporuje přístup ke kameře. Vyberte prosím fotografii.'
      : 'Pro použití kamery otevřete zabezpečenou adresu aplikace (HTTPS).';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    // A permission prompt can resolve after the user closes the camera dialog.
    if (request !== cameraRequest || !camera.value?.open) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    cameraStream = stream;
    video.value.srcObject = stream;
    await video.value.play();
    if (request === cameraRequest) cameraLoaded();
  } catch (cause) {
    if (request !== cameraRequest) return;
    stopCamera();
    cameraError.value = cause.name === 'NotAllowedError'
      ? 'Povolte prosím přístup ke kameře v nastavení prohlížeče.'
      : cause.name === 'NotFoundError'
        ? 'Kamera nebyla nalezena. Můžete vybrat fotografii ze souboru.'
        : 'Kameru se nepodařilo spustit. Zkuste ji otevřít znovu nebo vyberte fotografii.';
  }
}

function cameraLoaded() {
  cameraReady.value = Boolean(camera.value?.open && cameraStream && video.value?.videoWidth && video.value?.videoHeight);
}

function selectPhoto() {
  closeCamera();
  fileInput.value.click();
}

function jpegBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error('JPEG conversion failed')),
      'image/jpeg',
      0.95,
    );
  });
}

async function capturePhoto() {
  if (!cameraReady.value || cameraCapturing.value) return;
  const request = cameraRequest;
  cameraCapturing.value = true;
  try {
    const canvas = document.createElement('canvas');
    canvas.width = video.value.videoWidth;
    canvas.height = video.value.videoHeight;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas unavailable');
    context.drawImage(video.value, 0, 0);
    const image = await jpegBlob(canvas);
    if (request !== cameraRequest || !camera.value?.open) return;
    closeCamera();
    await uploadPhoto(image);
  } catch {
    if (request === cameraRequest) {
      cameraError.value = 'Fotku se nepodařilo pořídit. Zkuste to prosím znovu.';
    }
  } finally {
    if (request === cameraRequest) cameraCapturing.value = false;
  }
}

onMounted(() => window.addEventListener('pagehide', closeCamera));
onBeforeUnmount(() => {
  window.removeEventListener('pagehide', closeCamera);
  stopCamera();
});

function openMenu() {
  menu.value.showModal();
  menuOpen.value = true;
}

// Keep camera JPEGs intact for server-side EXIF normalization. Other formats
// supported by the browser need conversion because the API accepts raw JPEG bytes.
async function asJpeg(file) {
  if (file.type === 'image/jpeg') return file;
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas unavailable');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0);
    return await jpegBlob(canvas);
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function showError(message) {
  processed.value = false;
  error.value = typeof message === 'string' ? { error: message, details: '' } : message;
  scan.value = null;
  status.value = 'idle';
  await nextTick();
  captureButton.value.focus({ preventScroll: true });
}

async function scanPhoto(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (file) await uploadPhoto(file);
}

async function uploadPhoto(file) {
  if (status.value === 'uploading') return;
  status.value = 'uploading';
  progress.value = '';
  processed.value = false;
  error.value = null;
  try {
    const image = await asJpeg(file);
    const response = await fetch('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg' },
      body: image,
    });
    if (!response.ok) {
      await showError(await readApiError(response,
        'Formulář se nepodařilo zpracovat. Zkuste jej prosím vyfotit znovu.'));
      return;
    }
    for await (const result of readScanStream(response)) {
      if ('fatal' in result) {
        await showError(streamError(result));
      } else if (result.status === 'reviewing') {
        scan.value = result;
        status.value = 'review';
      } else if (result.status === 'finished') {
        await showSuccess();
      } else {
        showProgress(result.status);
      }
    }
  } catch {
    await showError('Fotku se nepodařilo odeslat nebo přečíst. Zkontrolujte připojení a zkuste to prosím znovu.');
  }
}

function showProgress(stage) {
  progress.value = stage;
  status.value = 'uploading';
}

async function showSuccess() {
  scan.value = null;
  status.value = 'idle';
  error.value = null;
  processed.value = true;
  await nextTick();
  captureButton.value.focus({ preventScroll: true });
}

</script>

<template>
  <div class="app-shell">
    <header class="site-header">
      <a class="brand" href="/" aria-label="Form Scanner — úvodní stránka">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none">
            <path d="M7 12V7h5m8 0h5v5m0 8v5h-5m-8 0H7v-5M12 13h8m-8 6h5" />
          </svg>
        </span>
        <span>Form Scanner</span>
      </a>
      <button
        class="icon-button" type="button" aria-label="Otevřít menu"
        aria-haspopup="dialog" aria-controls="main-menu"
        :aria-expanded="menuOpen" @click="openMenu"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M5 7h14M5 12h14M5 17h14" />
        </svg>
      </button>
    </header>

    <main :class="{ 'review-main': status === 'review' }">
      <ReviewPage
        v-if="scan" v-show="status === 'review'" :scan="scan"
        @processed="showSuccess" @error="showError"
        @progress="showProgress" @review="status = 'review'"
      />
      <section v-if="status !== 'review'" class="home-page" aria-label="Skenování formuláře">
        <div class="scan-area" :aria-busy="status === 'uploading'">
          <span class="orbit orbit-outer" aria-hidden="true"></span>
          <span class="orbit orbit-inner" aria-hidden="true"></span>
          <span class="orbit-dot" aria-hidden="true"></span>
          <button
            ref="captureButton" class="capture-button" type="button"
            :disabled="status === 'uploading'" @click="openCamera"
          >
            <template v-if="status === 'uploading'">
              <span class="spinner" aria-hidden="true"></span>
              <span>{{ progressLabel }}</span>
            </template>
            <template v-else>
              <svg class="camera-icon" viewBox="0 0 48 48" fill="none" aria-hidden="true">
                <path d="M17 12.5 20 8h8l3 4.5h6a5 5 0 0 1 5 5V35a5 5 0 0 1-5 5H11a5 5 0 0 1-5-5V17.5a5 5 0 0 1 5-5h6Z" />
                <circle cx="24" cy="26" r="8" /><path d="M35 19h.01" />
              </svg>
              <span>Vyfotit<br />formulář</span>
            </template>
          </button>
          <input
            ref="fileInput" class="visually-hidden" type="file" accept="image/*"
            tabindex="-1" aria-label="Fotografie formuláře"
            :disabled="status === 'uploading'" @change="scanPhoto"
          />
        </div>

        <div class="visually-hidden" role="status" aria-live="polite">
          <span v-if="status === 'uploading'">{{ progressLabel }}</span>
        </div>
        <p v-if="processed" class="success-message" role="status">
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>
          <span>Formulář úspěšně zpracován</span>
        </p>
        <ErrorMessage :message="error" />

      </section>
    </main>

    <dialog
      ref="camera" class="camera-dialog" aria-labelledby="camera-heading"
      @cancel.prevent="closeCamera" @close="cameraClosed" @click="closeCamera"
    >
      <div class="camera-panel" @click.stop>
        <div class="camera-header">
          <h2 id="camera-heading">Vyfotit formulář</h2>
          <button class="icon-button" type="button" aria-label="Zavřít kameru" @click="closeCamera">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
          </button>
        </div>
        <div class="camera-preview">
          <video ref="video" autoplay muted playsinline aria-label="Náhled kamery" @loadeddata="cameraLoaded"></video>
          <p v-if="!cameraReady && !cameraError" class="camera-opening" role="status">Spouštíme kameru…</p>
        </div>
        <p v-if="cameraError" class="error-message" role="alert">{{ cameraError }}</p>
        <div class="camera-actions">
          <button class="photo-button" type="button" :disabled="!cameraReady || cameraCapturing" @click="capturePhoto">Vyfotit</button>
          <button class="secondary-button" type="button" @click="selectPhoto">Vybrat fotografii</button>
        </div>
      </div>
    </dialog>

    <dialog
      id="main-menu" ref="menu" class="menu-dialog" aria-labelledby="menu-heading"
      @close="menuOpen = false" @click="menu.close()"
    >
      <div class="menu-panel" @click.stop>
        <div class="menu-header">
          <h2 id="menu-heading">Menu</h2>
          <button class="icon-button" type="button" aria-label="Zavřít menu" @click="menu.close()">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
          </button>
        </div>
        <nav aria-label="Hlavní navigace"></nav>
      </div>
    </dialog>
  </div>
</template>
