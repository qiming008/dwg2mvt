import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import qiankun from 'vite-plugin-qiankun'
import * as net from 'node:net'

const childMicroappName = 'cadView'

function probeUrl(target: string, timeoutMs = 250) {
  const url = new URL(target)
  const port = Number(url.port || (url.protocol === 'https:' ? 443 : 80))

  return new Promise<boolean>((resolve) => {
    const socket = net.createConnection({ host: url.hostname, port }, () => {
      socket.destroy()
      resolve(true)
    })

    socket.setTimeout(timeoutMs)
    socket.on('timeout', () => {
      socket.destroy()
      resolve(false)
    })
    socket.on('error', () => resolve(false))
  })
}

async function resolveApiTarget(envTarget?: string) {
  const candidates = [envTarget, 'http://127.0.0.1:8088', 'http://localhost:8088', 'http://127.0.0.1:8000', 'http://localhost:8000', 'http://172.24.4.66:19010'].filter(
    Boolean,
  ) as string[]

  for (const candidate of candidates) {
    try {
      if (await probeUrl(candidate)) {
        return candidate
      }
    } catch {
      // Ignore malformed targets and continue to the next fallback.
    }
  }

  return candidates[0] || 'http://127.0.0.1:8088'
}

async function resolveGeoServerTarget(envTarget?: string) {
  const candidates = [envTarget, 'http://127.0.0.1:19080', 'http://localhost:19080', 'http://172.24.4.66:19080'].filter(
    Boolean,
  ) as string[]

  for (const candidate of candidates) {
    try {
      if (await probeUrl(candidate)) {
        return candidate
      }
    } catch {
      // Ignore malformed targets and continue to the next fallback.
    }
  }

  return candidates[0] || 'http://127.0.0.1:19080'
}

export default defineConfig(async ({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const autoProxy = env.VITE_AUTO_PROXY === '1'
  const apiTarget = autoProxy
    ? await resolveApiTarget(env.VITE_API_TARGET || env.VITE_BACKEND_URL)
    : env.VITE_API_TARGET || env.VITE_BACKEND_URL || 'http://127.0.0.1:8088'
  const geoserverTarget = autoProxy
    ? await resolveGeoServerTarget(env.VITE_GEOSERVER_TARGET)
    : env.VITE_GEOSERVER_TARGET || 'http://127.0.0.1:19080'
  const devPort = Number(env.VITE_DEV_PORT || 3666)
  const publicBase = env.VITE_PUBLIC_BASE || (command === 'build' ? `/${childMicroappName}/` : '/')

  return {
    base: publicBase,
    plugins: [vue(), qiankun(childMicroappName, { useDevMode: true })],
    server: {
      host: '0.0.0.0',
      port: devPort,
      cors: true,
      headers: {
        'Access-Control-Allow-Origin': '*',
      },
      proxy: {
        '/csrap_mapapi': {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/csrap_mapapi/, '/api'),
        },
        '/jy-csp-gis': { target: apiTarget, changeOrigin: true },
        '/geoserver': { target: geoserverTarget, changeOrigin: true },
        '/csrap_geoserver': {
          target: geoserverTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/csrap_geoserver/, '/geoserver'),
        },
      },
    },
    build: {
      outDir: childMicroappName,
      assetsDir: 'static',
    },
  }
})
