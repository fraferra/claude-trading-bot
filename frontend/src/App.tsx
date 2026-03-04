import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Strategies from './pages/Strategies';
import Trade from './pages/Trade';
import Markets from './pages/Markets';
import Monitors from './pages/Monitors';
import Activity from './pages/Activity';
import SettingsPage from './pages/SettingsPage';
import ResearchAgent from './pages/ResearchAgent';
import Kalshi from './pages/Kalshi';
import Crypto from './pages/Crypto';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 10_000,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/research" element={<ResearchAgent />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/trade" element={<Trade />} />
            <Route path="/markets" element={<Markets />} />
            <Route path="/kalshi" element={<Kalshi />} />
            <Route path="/crypto" element={<Crypto />} />
            <Route path="/monitors" element={<Monitors />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
