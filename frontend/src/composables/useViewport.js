import { onBeforeUnmount, onMounted, ref } from 'vue'

const MOBILE_MAX_WIDTH = 767

function getMediaQuery() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  return window.matchMedia(`(max-width: ${MOBILE_MAX_WIDTH}px)`)
}

/**
 * Reactive viewport classification used by the application shell.
 * The mobile shell intentionally has a hard 767px boundary so a tablet/PC
 * never receives the phone navigation chrome by accident.
 */
export function useViewport() {
  const mediaQuery = getMediaQuery()
  const isMobile = ref(mediaQuery ? mediaQuery.matches : typeof window !== 'undefined' && window.innerWidth <= MOBILE_MAX_WIDTH)

  function update() {
    isMobile.value = mediaQuery ? mediaQuery.matches : typeof window !== 'undefined' && window.innerWidth <= MOBILE_MAX_WIDTH
  }

  onMounted(() => {
    if (!mediaQuery) {
      window.addEventListener('resize', update, { passive: true })
      update()
      return
    }
    update()
    if (typeof mediaQuery.addEventListener === 'function') mediaQuery.addEventListener('change', update)
    else mediaQuery.addListener?.(update)
  })

  onBeforeUnmount(() => {
    if (!mediaQuery) {
      window.removeEventListener('resize', update)
      return
    }
    if (typeof mediaQuery.removeEventListener === 'function') mediaQuery.removeEventListener('change', update)
    else mediaQuery.removeListener?.(update)
  })

  return { isMobile }
}

export default useViewport
