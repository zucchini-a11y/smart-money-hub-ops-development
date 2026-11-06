import { createRoot } from 'react-dom/client';
import { Router } from 'wouter';
import PublicSite from './public-site/PublicSite';

createRoot(document.getElementById('root')!).render(
  <Router>
    <PublicSite />
  </Router>,
);
