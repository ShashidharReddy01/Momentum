import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MomentumApp } from '@/index';

const el = document.getElementById('root');
if (!el) throw new Error('#root not found');

createRoot(el).render(
  <StrictMode>
    <MomentumApp basePath={import.meta.env.VITE_MOMENTUM_BASE_PATH ?? ''} />
  </StrictMode>,
);
