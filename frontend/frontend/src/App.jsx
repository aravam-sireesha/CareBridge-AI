import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import ForgotPassword from './pages/ForgotPassword.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Children from './pages/Children.jsx'
import ChildProfile from './pages/ChildProfile.jsx'
import Needs from './pages/Needs.jsx'
import People from './pages/People.jsx'
import Donations from './pages/Donations.jsx'
import NeedAlerts from './pages/NeedAlerts.jsx'
import FraudFlags from './pages/FraudFlags.jsx'
import MatchingReview from './pages/MatchingReview.jsx'
import CareerGuidance from './pages/CareerGuidance.jsx'
import Assistant from './pages/Assistant.jsx'
import Settings from './pages/Settings.jsx'
import { AdminLogin, AdminSetup } from './pages/AdminAuth.jsx'
import AdminVerification from './pages/AdminVerification.jsx'
import AdminUsers from './pages/AdminUsers.jsx'
import AdminAnomalies from './pages/AdminAnomalies.jsx'
import AdminPeople from './pages/AdminPeople.jsx'
import BulkUpload from './pages/BulkUpload.jsx'
import Reports from './pages/Reports.jsx'
import Notifications from './pages/Notifications.jsx'
import AdminOverview from './pages/AdminOverview.jsx'
import AdminNeeds from './pages/AdminNeeds.jsx'
import AdminSuggestions from './pages/AdminSuggestions.jsx'
import AdminOrganizations from './pages/AdminOrganizations.jsx'
import AdminDonors from './pages/AdminDonors.jsx'
import AdminTeam from './pages/AdminTeam.jsx'
import AdminHub from './pages/AdminHub.jsx'
import Guide from './pages/Guide.jsx'
import AdminAILab from './pages/AdminAILab.jsx'
import AdminVolunteers from './pages/AdminVolunteers.jsx'
import AdminWorkflow from './pages/AdminWorkflow.jsx'
import AdminReview from './pages/AdminReview.jsx'
import AdminResources from './pages/AdminResources.jsx'
import AdminAudit from './pages/AdminAudit.jsx'
import Resources from './pages/Resources.jsx'

const guard = (el, roles) => <ProtectedRoute roles={roles}>{el}</ProtectedRoute>
const adminGuard = (el) => <ProtectedRoute roles={['admin']} loginPath="/admin/login">{el}</ProtectedRoute>

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/guide" element={<Guide />} />
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route path="/admin/setup" element={<AdminSetup />} />
      {/* Familiar names for existing pages (no duplicate screens) */}
      <Route path="/admin/dashboard" element={<Navigate to="/admin/overview" replace />} />
      <Route path="/admin/audit-logs" element={<Navigate to="/admin/audit" replace />} />
      <Route path="/admin/settings" element={<Navigate to="/settings" replace />} />
      <Route path="/admin/children" element={<Navigate to="/children" replace />} />
      <Route path="/admin/donations" element={<Navigate to="/donations" replace />} />
      <Route path="/admin/reports" element={<Navigate to="/reports" replace />} />
      <Route path="/admin/fraud" element={<Navigate to="/ai/fraud" replace />} />
      <Route path="/admin" element={adminGuard(<AdminWorkflow />)} />
      <Route path="/admin/overview" element={adminGuard(<AdminOverview />)} />
      <Route path="/admin/review" element={adminGuard(<AdminReview />)} />
      <Route path="/admin/ai-lab" element={adminGuard(<AdminAILab />)} />
      <Route path="/admin/resources" element={adminGuard(<AdminResources />)} />
      <Route path="/admin/audit" element={adminGuard(<AdminAudit />)} />
      <Route path="/resources" element={guard(<Resources />, ['organization'])} />
      <Route path="/admin/needs" element={adminGuard(<AdminNeeds />)} />
      <Route path="/admin/suggestions" element={adminGuard(<AdminSuggestions />)} />
      <Route path="/admin/organizations" element={adminGuard(<AdminOrganizations />)} />
      <Route path="/admin/donors" element={adminGuard(<AdminDonors />)} />
      <Route path="/admin/volunteers" element={adminGuard(<AdminVolunteers />)} />
      <Route path="/admin/recommend" element={adminGuard(<AdminHub />)} />
      <Route path="/admin/team" element={adminGuard(<AdminTeam />)} />
      <Route path="/admin/verification" element={adminGuard(<AdminVerification />)} />
      <Route path="/admin/users" element={adminGuard(<AdminUsers />)} />
      <Route path="/admin/anomalies" element={adminGuard(<AdminAnomalies />)} />
      <Route path="/admin/people" element={adminGuard(<AdminPeople />)} />

      <Route path="/dashboard" element={guard(<Dashboard />)} />
      <Route path="/children" element={guard(<Children />, ['admin', 'organization'])} />
      <Route path="/children/:id" element={guard(<ChildProfile />, ['admin', 'organization'])} />
      <Route path="/needs" element={guard(<Needs />)} />
      <Route path="/needs/bulk" element={guard(<BulkUpload />, ['admin', 'organization'])} />
      <Route path="/reports" element={guard(<Reports />, ['admin', 'organization'])} />
      <Route path="/notifications" element={guard(<Notifications />)} />
      <Route path="/people" element={guard(<People />, ['admin', 'organization'])} />
      <Route path="/donations" element={guard(<Donations />, ['admin', 'organization', 'donor'])} />
      <Route path="/ai/needs-alerts" element={guard(<NeedAlerts />, ['admin', 'organization'])} />
      <Route path="/ai/fraud" element={guard(<FraudFlags />, ['admin'])} />
      <Route path="/ai/matching" element={guard(<MatchingReview />, ['admin', 'organization'])} />
      <Route path="/ai/career" element={guard(<CareerGuidance />, ['admin', 'organization'])} />
      <Route path="/assistant" element={guard(<Assistant />)} />
      <Route path="/settings" element={guard(<Settings />)} />
      <Route path="/ai" element={<Navigate to="/ai/needs-alerts" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
