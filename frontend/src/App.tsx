import { Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import { Loading } from './components/UI'
import { AppLayout } from './layouts/AppLayout'
import { AnalysesPage } from './pages/AnalysesPage'
import { AnalysisDetailPage } from './pages/AnalysisDetailPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { ModelsPage } from './pages/ModelsPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { UsersPage } from './pages/UsersPage'

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (!user) return <LoginPage />
  return <Routes>
    <Route element={<AppLayout />}>
      <Route index element={<DashboardPage />} />
      <Route path="projects" element={<ProjectsPage />} />
      <Route path="analyses" element={<AnalysesPage />} />
      <Route path="analyses/:id" element={<AnalysisDetailPage />} />
      <Route path="models" element={<ModelsPage />} />
      <Route path="users" element={<UsersPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Route>
  </Routes>
}
