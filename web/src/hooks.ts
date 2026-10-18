import { useEffect, useState } from 'react'

/** Charge une ressource puis la rafraîchit toutes les `intervalMs` millisecondes. */
export function usePolling<T>(load: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const run = async () => {
      try {
        const value = await load()
        if (alive) {
          setData(value)
          setError(null)
        }
      } catch (e) {
        if (alive) setError((e as Error).message)
      }
    }
    run()
    const id = window.setInterval(run, intervalMs)
    return () => {
      alive = false
      window.clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error }
}

/** Thème clair/sombre du système, pour reconstruire les graphiques quand il change. */
export function useColorScheme() {
  const query = '(prefers-color-scheme: dark)'
  const [dark, setDark] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const onChange = () => setDark(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return dark ? 'dark' : 'light'
}
