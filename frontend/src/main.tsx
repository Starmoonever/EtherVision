import { createRoot } from 'react-dom/client';
import './theme/tokens.css';
import './index.css';
import './shared/styles/layout.css';
import './shared/styles/components.css';
import App from './App.tsx';

createRoot(document.getElementById('root')!).render(<App />);
