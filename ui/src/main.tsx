import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import { queryClient } from './api'

import Health from './Health.tsx'
import ProviderDashboard from './ProviderDashboard.tsx'
import PatientDashboard from './PatientDashboard.tsx'

createRoot(document.getElementById('root')!).render(
	<StrictMode>
		<BrowserRouter>
			<QueryClientProvider client={queryClient}>
				<Routes>
					<Route path="/" element={<Navigate to="/provider" replace />} />
					<Route path="/provider" element={<ProviderDashboard />} />
					<Route path="/patient/:patientId" element={<PatientDashboard />} />
					<Route path="/health" element={<Health />} />
					<Route path="*" element={<Navigate to="/provider" replace />} />
				</Routes>
			</QueryClientProvider>
		</BrowserRouter>
	</StrictMode>,
)
