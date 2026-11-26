<script setup>
defineProps({ message: { type: Object, default: null } });
</script>

<template>
  <div v-if="message" class="error-message" role="alert">
    <p class="error-title">{{ message.error }}</p>
    <p v-if="message.details" class="error-details">{{ message.details }}</p>
  </div>
</template>
