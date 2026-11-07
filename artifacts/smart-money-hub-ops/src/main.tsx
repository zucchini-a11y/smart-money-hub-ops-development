import { createRoot } from 'react-dom/client';

import App from './PortalApp';
import { ErrorBoundary } from '@/components/error-boundary';

import './portal-theme.css';
import './vayda-consistency.css';

createRoot(document.getElementById('root')!, {
  // Keeps caught errors off reportError(), which would raise the dev overlay.
  onCaughtError: (error, errorInfo) => {
    console.error(error, errorInfo.componentStack);
  },
}).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
