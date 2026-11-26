<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';

const props = defineProps({ scan: { type: Object, required: true } });
const emit = defineEmits(['processed', 'restart']);
const heading = ref(null);
const submitting = ref(false);
const error = ref('');
const failed = ref(false);
const controller = new AbortController();
const fields = ref(props.scan.reviews.map((field) => ({
  ...field,
  input: field.type === 'Name'
    ? { first_name: field.value?.first_name ?? '', surname: field.value?.surname ?? '' }
    : field.type === 'bool' ? field.value === true
      : field.type === 'date' && field.value ? displayDate(field.value) : String(field.value ?? ''),
  crop: null,
  cropError: false,
  touched: false,
})));

function displayDate(value) {
  const [year, month, day] = value.split('-');
  return `${Number(day)}.${Number(month)}.${year}`;
}

function isoDate(value) {
  const match = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(value.trim());
  if (!match) return null;
  const [, day, month, year] = match;
  if (Number(year) < 1) return null;
  const iso = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === iso ? iso : null;
}

function validationError(field) {
  const value = typeof field.input === 'string' ? field.input.trim() : field.input;
  if (value === '') return '';
  if (field.type === 'int' && (!/^[+-]?\d+$/.test(value) || !Number.isSafeInteger(Number(value)))) {
    return 'Zadejte celé číslo.';
  }
  if (field.type === 'Decimal' && !/^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$/.test(value)) {
    return 'Zadejte desetinné číslo s tečkou nebo čárkou.';
  }
  if (field.type === 'date' && !isoDate(value)) return 'Zadejte platné datum ve formátu D.M.YYYY.';
  return '';
}

function correctedValue(field) {
  if (field.type === 'Name') {
    return { first_name: field.input.first_name || null, surname: field.input.surname || null };
  }
  if (field.type === 'bool') return field.input;
  if (field.input.trim() === '') return null;
  if (field.type === 'int') return Number(field.input);
  if (field.type === 'Decimal') {
    let decimal = field.input.trim().replace(',', '.');
    decimal = decimal.replace(/^([+-]?)\./, (_match, sign) => `${sign}0.`);
    return decimal.endsWith('.') ? `${decimal}0` : decimal;
  }
  return field.type === 'date' ? isoDate(field.input) : field.input;
}

async function loadCrop(field) {
  if (!field.bounding_box) return;
  field.cropError = false;
  try {
    const response = await fetch(`/api/scan/field?session_id=${encodeURIComponent(props.scan.session_id)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(field.bounding_box),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error('Crop unavailable');
    const blob = await response.blob();
    if (!controller.signal.aborted) field.crop = URL.createObjectURL(blob);
  } catch {
    if (!controller.signal.aborted) field.cropError = true;
  }
}

async function submit() {
  if (submitting.value || failed.value) return;
  fields.value.forEach((field) => { field.touched = true; });
  if (fields.value.some(validationError)) {
    await nextTick();
    document.querySelector('.review-page [aria-invalid="true"]')?.focus();
    return;
  }
  submitting.value = true;
  error.value = '';
  try {
    const response = await fetch('/api/scan/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: props.scan.session_id,
        reviews: fields.value.map((field) => ({ path: field.path, value: correctedValue(field) })),
      }),
    });
    if (response.ok) {
      emit('processed');
    } else if (response.status === 422) {
      error.value = 'Některou hodnotu se nepodařilo ověřit. Zkontrolujte pole a odešlete je znovu.';
    } else {
      failed.value = true;
      error.value = 'Formulář se nepodařilo zpracovat. Naskenujte jej prosím znovu.';
    }
  } catch {
    failed.value = true;
    error.value = 'Spojení bylo přerušeno. Nelze ověřit, zda byl formulář zpracován.';
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  heading.value.focus();
  fields.value.forEach(loadCrop);
});
onBeforeUnmount(() => {
  controller.abort();
  fields.value.forEach((field) => { if (field.crop) URL.revokeObjectURL(field.crop); });
});
</script>

<template>
  <section class="review-page" aria-labelledby="review-heading">
    <h1 id="review-heading" ref="heading" tabindex="-1">Zkontroluj tato pole</h1>
    <form novalidate :aria-busy="submitting" @submit.prevent="submit">
      <div class="review-table">
        <div v-for="(field, index) in fields" :key="field.path" class="review-row" role="group" :aria-labelledby="`label-${index}`">
          <h2 :id="`label-${index}`">{{ field.label }}</h2>
          <div class="review-columns">
            <div class="field-crop">
              <img v-if="field.crop" :src="field.crop" :alt="`Výřez: ${field.label}`" />
              <template v-else-if="field.cropError">
                <span>Výřez se nepodařilo načíst.</span>
                <button type="button" class="crop-retry" @click="loadCrop(field)">Zkusit znovu</button>
              </template>
              <span v-else-if="!field.bounding_box">Výřez není k dispozici.</span>
              <span v-else class="crop-loading" role="status" :aria-label="`Načítání výřezu: ${field.label}`"><span class="spinner" aria-hidden="true"></span></span>
            </div>
            <div class="field-editor">
              <div v-if="field.type === 'Name'" class="name-inputs">
                <label><span>Jméno</span><input v-model="field.input.first_name" type="text" :aria-label="`${field.label}: Jméno`" :disabled="submitting || failed" /></label>
                <label><span>Příjmení</span><input v-model="field.input.surname" type="text" :aria-label="`${field.label}: Příjmení`" :disabled="submitting || failed" /></label>
              </div>
              <label v-else-if="field.type === 'bool'" class="checkbox-field">
                <input v-model="field.input" type="checkbox" :aria-labelledby="`label-${index}`" :disabled="submitting || failed" />
                <span>Ano</span>
              </label>
              <div v-else class="text-editor">
                <input
                  :id="`value-${index}`" v-model="field.input" type="text"
                  :inputmode="field.type === 'int' ? 'numeric' : field.type === 'Decimal' ? 'decimal' : 'text'"
                  :placeholder="field.type === 'date' ? 'D.M.YYYY' : undefined"
                  :aria-labelledby="`label-${index}`" :aria-describedby="field.touched && validationError(field) ? `error-${index}` : undefined"
                  :aria-invalid="Boolean(field.touched && validationError(field))" :disabled="submitting || failed"
                  @blur="field.touched = true"
                />
                <label v-if="field.type === 'date'" class="calendar-picker">
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="5" width="16" height="16" rx="2" /><path d="M8 3v4m8-4v4M4 11h16" /></svg>
                  <input type="date" @click="$event.target.showPicker?.()" :aria-label="`Vybrat datum: ${field.label}`" :value="isoDate(field.input) || ''" :disabled="submitting || failed" @change="field.input = $event.target.value ? displayDate($event.target.value) : ''; field.touched = true" />
                </label>
              </div>
              <p v-if="field.touched && validationError(field)" :id="`error-${index}`" class="field-error" role="alert">{{ validationError(field) }}</p>
            </div>
          </div>
        </div>
      </div>
      <p v-if="error" class="error-message" role="alert">{{ error }}</p>
      <button v-if="failed" class="photo-button review-submit" type="button" @click="emit('restart')">Naskenovat znovu</button>
      <button v-else class="photo-button review-submit" type="submit" :disabled="submitting">
        <span v-if="submitting" class="spinner" aria-hidden="true"></span>
        {{ submitting ? 'Zpracováváme…' : 'Odeslat' }}
      </button>
      <span class="visually-hidden" role="status">{{ submitting ? 'Zpracováváme formulář…' : '' }}</span>
    </form>
  </section>
</template>
