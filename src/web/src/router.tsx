import { lazy, Suspense, type ComponentType } from 'react'
import { createBrowserRouter } from 'react-router'
import { MilhouseLoader } from '@/components/milhouse/Glasses'
import { AppShell } from '@/components/shell/AppShell'
import { AnnunciPage } from '@/features/listings/AnnunciPage'

// The feed loads with the shell; every other section is fetched when first opened.
function page(load: () => Promise<{ default: ComponentType }>) {
  const Page = lazy(load)
  return (
    <Suspense fallback={<MilhouseLoader className="p-8" lines={['Milhouse apre la pagina…', 'Quasi fatto…']} />}>
      <Page />
    </Suspense>
  )
}

const map = page(() => import('@/features/map/MapPage').then((m) => ({ default: m.MapPage })))
const compare = page(() => import('@/features/compare/ComparePage').then((m) => ({ default: m.ComparePage })))
const searches = page(() => import('@/features/searches/SearchesPage').then((m) => ({ default: m.SearchesPage })))
const configForm = page(() => import('@/features/searches/ConfigFormPage').then((m) => ({ default: m.ConfigFormPage })))
const runs = page(() => import('@/features/runs/RunsPage').then((m) => ({ default: m.RunsPage })))
const preferences = page(() => import('@/features/preferences/PreferencesPage').then((m) => ({ default: m.PreferencesPage })))

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <AnnunciPage /> },
      { path: 'annunci/:id', element: <AnnunciPage /> },
      { path: 'mappa', element: map },
      { path: 'confronta', element: compare },
      { path: 'ricerche', element: searches },
      { path: 'ricerche/nuova', element: configForm },
      { path: 'ricerche/:id', element: configForm },
      { path: 'run', element: runs },
      { path: 'run/:id', element: runs },
      { path: 'preferenze', element: preferences },
      { path: '*', element: <AnnunciPage /> },
    ],
  },
])
