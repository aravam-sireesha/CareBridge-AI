import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import LiveConnection from './components/LiveConnection.jsx'
import PwaBoot from './components/PwaBoot.jsx'
import { getInstallController, registerServiceWorker } from './lib/pwa.js'
import { initMonitoring } from './lib/monitoring.js'
import { ThemeProvider } from './context/ThemeContext.jsx'
import { ToastProvider } from './context/ToastContext.jsx'
import './index.css'
import './dark.css'
import './styles/aiux.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>
            <LiveConnection />
            <PwaBoot />
            <App />
          </AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
)

// Created before React renders: the browser may fire its install prompt event at any moment after load.
getInstallController()
initMonitoring()      // no-op unless VITE_SENTRY_DSN is set
registerServiceWorker({ onUpdate: (registration) => window.dispatchEvent(new CustomEvent('cb:sw-update', { detail: registration })) })
