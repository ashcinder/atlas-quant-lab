import { createRoot } from 'react-dom/client'
import AtlasShell from './AtlasShell'
import './journal/styles/utilities.css'
import './styles.css'
import './workspace.css'
import './operations.css'
import './journal/styles/journal.css'
import './shell.css'
import './terminal-density.css'
import { applyAppearance } from './components/AppearanceSettings'

applyAppearance()

// The app is normally run through Vite on a personal workstation. Rendering
// once avoids React's development-only double data fetch while preserving the
// same production behavior.
createRoot(document.getElementById('root')!).render(<AtlasShell />)
