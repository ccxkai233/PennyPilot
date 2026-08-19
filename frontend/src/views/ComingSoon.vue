<template>
  <AppLayout :title="title" subtitle="功能模块">
    <section class="coming panel">
      <div class="coming-icon">✦</div>
      <h2>{{ title }}正在准备中</h2>
      <p>{{ description }}</p>
      <router-link class="primary" to="/ai">先去记一笔</router-link>
    </section>
  </AppLayout>
</template>

<script setup>
import AppLayout from '../components/AppLayout.vue'
defineProps({ title: { type: String, default: '此功能' }, description: { type: String, default: '' } })
</script>

<style scoped>
.panel { background: #fff; border-radius: 13px; box-shadow: 0 2px 8px #243b5a0d; }.coming { margin-top: 28px; min-height: 360px; display: grid; place-content: center; text-align: center; padding: 32px; }.coming-icon { width: 58px; height: 58px; margin: 0 auto 17px; display: grid; place-items: center; border-radius: 18px; color: #2563eb; background: #edf4ff; font-size: 27px; }.coming h2 { margin: 0; color: #33425b; font-size: 20px; }.coming p { color: #8a97aa; font-size: 13px; margin: 10px 0 23px; }.primary { display: inline-block; border-radius: 8px; background: #2563eb; color: white; padding: 11px 20px; font-size: 13px; font-weight: 600; text-decoration: none; }
</style>
