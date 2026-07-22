<script setup>
  import { ref, onBeforeUnmount, watch, nextTick } from 'vue'
  import { ChevronDown } from 'lucide-vue-next'

  const props = defineProps({
    modelValue: { type: String, default: '' },
    options: { type: Array, default: () => [] },
    placeholder: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
    id: { type: String, default: '' }
  })

  const emit = defineEmits(['update:modelValue'])

  const containerRef = ref(null)
  const isOpen = ref(false)

  const selectedLabel = () => {
    const opt = props.options.find((o) => o.value === props.modelValue)
    return opt ? opt.label : props.placeholder || ''
  }

  const toggle = () => {
    if (props.disabled || props.options.length === 0) return
    isOpen.value = !isOpen.value
  }

  const select = (value) => {
    emit('update:modelValue', value)
    isOpen.value = false
  }

  const onOutsideMousedown = (e) => {
    if (containerRef.value && !containerRef.value.contains(e.target)) {
      isOpen.value = false
    }
  }

  watch(isOpen, (open) => {
    nextTick(() => {
      if (open) {
        document.addEventListener('mousedown', onOutsideMousedown)
      } else {
        document.removeEventListener('mousedown', onOutsideMousedown)
      }
    })
  })

  onBeforeUnmount(() => {
    document.removeEventListener('mousedown', onOutsideMousedown)
  })
</script>

<template>
  <div ref="containerRef" class="custom-select" :class="{ open: isOpen }">
    <button
      :id="id"
      type="button"
      class="custom-select-trigger"
      :disabled="disabled || options.length === 0"
      :aria-expanded="isOpen ? 'true' : 'false'"
      aria-haspopup="listbox"
      @click="toggle"
    >
      <span class="custom-select-trigger-text">{{ selectedLabel() }}</span>
      <ChevronDown
        :size="16"
        class="custom-select-chevron"
        :class="{ open: isOpen }"
      />
    </button>
    <transition name="slide-down">
      <div v-if="isOpen" class="custom-select-popup" role="listbox">
        <button
          v-for="opt in options"
          :key="opt.value"
          type="button"
          class="custom-select-option"
          :class="{ active: opt.value === modelValue }"
          role="option"
          :aria-selected="opt.value === modelValue ? 'true' : 'false'"
          @click="select(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>
    </transition>
  </div>
</template>

<style scoped>
  .custom-select {
    position: relative;
    width: 100%;
    min-width: 0;
  }

  .custom-select-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    min-height: 38px;
    padding: 6px 10px;
    border: 1.5px solid rgba(148, 163, 184, 0.45);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text-soft, #334155);
    font-size: 0.83rem;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    transition: border-color 0.18s;
  }

  .custom-select-trigger:hover:not(:disabled) {
    border-color: var(--brand, #0d9488);
  }

  .custom-select-trigger:focus-visible {
    outline: none;
    border-color: var(--brand, #0d9488);
    box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.1);
  }

  .custom-select-trigger:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .custom-select-trigger-text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .custom-select-chevron {
    flex-shrink: 0;
    color: #64748b;
    transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
  }

  .custom-select-chevron.open {
    transform: rotate(180deg);
  }

  .custom-select-popup {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 20;
    min-width: 100%;
    max-height: 260px;
    overflow-y: auto;
    background: #fff;
    border: 1.5px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .custom-select-option {
    display: flex;
    align-items: center;
    width: 100%;
    padding: 7px 10px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: var(--text-soft, #334155);
    font-size: 0.84rem;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    transition: background 0.15s;
  }

  .custom-select-option:hover {
    background: var(--brand-soft, #e6fffb);
  }

  .custom-select-option.active {
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-weight: 600;
  }

  .custom-select-option:focus-visible {
    outline: none;
    box-shadow: inset 0 0 0 2px var(--brand, #0d9488);
  }

  .slide-down-enter-active {
    animation: slide-down-in 0.3s cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  .slide-down-leave-active {
    animation: slide-down-in 0.2s cubic-bezier(0.22, 1, 0.36, 1) reverse both;
  }

  @keyframes slide-down-in {
    from {
      opacity: 0;
      transform: translateY(-6px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
</style>
