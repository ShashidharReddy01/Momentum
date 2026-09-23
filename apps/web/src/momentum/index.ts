/** Public entry point of the embeddable Momentum UI module (ADR-0006). */
export { MomentumApp } from './MomentumApp';
export type { MomentumAppProps } from './MomentumApp';
export { MomentumProvider } from './providers/MomentumProvider';
export { buildRoutes as momentumRoutes } from './routes';
export type { RuntimeConfig } from './lib/config';
