import { createApp } from 'vue'
import { renderWithQiankun, qiankunWindow, type QiankunProps } from 'vite-plugin-qiankun/dist/helper'
import './style.css'
import App from './App.vue'
import { clearRuntimeAuthToken, setRuntimeAuthToken, setRuntimeOrgNode } from './utils/auth'

let app: ReturnType<typeof createApp> | null = null

type CadViewQiankunProps = QiankunProps & {
  getters?: {
    access_token?: string
    currentOrgTreeNode?: unknown
  }
  onGlobalStateChange?: (callback: (state: Record<string, any>, prevState: Record<string, any>) => void, fireImmediately?: boolean) => void
}

function applyQiankunToken(props: CadViewQiankunProps) {
  setRuntimeAuthToken(props.getters?.access_token)
}

function applyQiankunOrgNode(props: CadViewQiankunProps) {
  setRuntimeOrgNode(props.getters?.currentOrgTreeNode)
  window.__CAD_VIEW_QIANKUN_ORG_NODE__ = props.getters?.currentOrgTreeNode
}

function render(props: QiankunProps = {}) {
  const { container } = props
  const mountPoint = container ? container.querySelector('#app') : document.querySelector('#app')

  if (!mountPoint) {
    return
  }

  app = createApp(App)
  app.mount(mountPoint as Element)
}

if (!qiankunWindow.__POWERED_BY_QIANKUN__) {
  render()
}

renderWithQiankun({
  bootstrap() {
    // no-op
  },
  mount(props: CadViewQiankunProps) {
    applyQiankunToken(props)
    applyQiankunOrgNode(props)
    props.onGlobalStateChange?.((state) => {
      const nextToken = typeof state?.access_token === 'string' ? state.access_token : ''
      setRuntimeAuthToken(nextToken)
      setRuntimeOrgNode(state?.currentOrgTreeNode)
      window.__CAD_VIEW_QIANKUN_ORG_NODE__ = state?.currentOrgTreeNode
    }, true)
    render(props)
  },
  update(props: CadViewQiankunProps) {
    applyQiankunToken(props)
    applyQiankunOrgNode(props)
  },
  unmount() {
    clearRuntimeAuthToken()
    app?.unmount()
    app = null
    const root = document.querySelector('#app')
    if (root) {
      root.innerHTML = ''
    }
  },
})
