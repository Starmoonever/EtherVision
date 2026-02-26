import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync, existsSync } from 'fs'
import { load } from 'js-yaml'
import { resolve } from 'path'

// 读取 config.yaml（不存在时静默跳过，使用空值）
interface AppConfig {
  rpc_url?: string
}

function loadConfig(): AppConfig {
  const configPath = resolve(__dirname, 'config.yaml')
  if (!existsSync(configPath)) return {}
  try {
    return (load(readFileSync(configPath, 'utf8')) as AppConfig) ?? {}
  } catch {
    return {}
  }
}

const appConfig = loadConfig()

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    // 注入为 import.meta.env.VITE_RPC_URL，与代码中的读取方式保持一致
    'import.meta.env.VITE_RPC_URL': JSON.stringify(appConfig.rpc_url ?? ''),
  },
})
