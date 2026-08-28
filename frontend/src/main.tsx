import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

// The app is normally run through Vite on a personal workstation. Rendering
// once avoids React's development-only double data fetch while preserving the
// same production behavior.
createRoot(document.getElementById('root')!).render(<App />)
