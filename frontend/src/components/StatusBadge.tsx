const colors: Record<string, string> = {
  running: 'bg-green-500/20 text-green-400',
  paused: 'bg-yellow-500/20 text-yellow-400',
  stopped: 'bg-slate-500/20 text-slate-400',
  error: 'bg-red-500/20 text-red-400',
  buy: 'bg-green-500/20 text-green-400',
  sell: 'bg-red-500/20 text-red-400',
  hold: 'bg-yellow-500/20 text-yellow-400',
  filled: 'bg-green-500/20 text-green-400',
  pending: 'bg-yellow-500/20 text-yellow-400',
};

export default function StatusBadge({ status }: { status: string }) {
  const c = colors[status.toLowerCase()] || 'bg-slate-500/20 text-slate-400';
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${c}`}>
      {status.toUpperCase()}
    </span>
  );
}
