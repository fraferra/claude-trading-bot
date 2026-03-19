import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard, LineChart, ArrowRightLeft, Globe,
  Radio, History, Settings, Wifi, WifiOff, Brain,
  TrendingUp, TrendingDown, Bitcoin, BarChart3, Shield, FlaskConical, Target,
} from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/research', icon: Brain, label: 'Research Agent' },
  { to: '/strategies', icon: LineChart, label: 'Strategies' },
  { to: '/trade', icon: ArrowRightLeft, label: 'Trade' },
  { to: '/markets', icon: Globe, label: 'Markets' },
  { to: '/kalshi', icon: TrendingUp, label: 'Kalshi' },
  { to: '/polymarket', icon: Target, label: 'Polymarket' },
  { to: '/crypto', icon: Bitcoin, label: 'Crypto' },
  { to: '/shorts', icon: TrendingDown, label: 'Shorts' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/risk', icon: Shield, label: 'Risk' },
  { to: '/backtest', icon: FlaskConical, label: 'Backtest' },
  { to: '/monitors', icon: Radio, label: 'Monitors' },
  { to: '/activity', icon: History, label: 'Activity' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function Layout() {
  const { connected } = useWebSocket();

  return (
    <div className="flex h-screen">
      <nav className="w-56 bg-slate-900 border-r border-slate-800 flex flex-col">
        <div className="p-4 border-b border-slate-800">
          <h1 className="text-lg font-bold text-white">Trading Bot</h1>
          <div className="flex items-center gap-1.5 mt-1 text-xs text-slate-400">
            {connected ? (
              <><Wifi size={12} className="text-green-400" /> Connected</>
            ) : (
              <><WifiOff size={12} className="text-red-400" /> Disconnected</>
            )}
          </div>
        </div>

        <div className="flex-1 py-2">
          {links.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-slate-800 text-white border-r-2 border-blue-500'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="flex-1 overflow-auto bg-slate-950 p-6">
        <Outlet />
      </main>
    </div>
  );
}
