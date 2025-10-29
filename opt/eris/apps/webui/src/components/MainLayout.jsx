import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

const navLinks = [
  { to: '/', label: 'Dashboard' },
  { to: '/media', label: 'Media Library' },
  { to: '/schedule', label: 'Scheduling' }
];

export default function MainLayout() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800/70 bg-slate-900/60 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-emerald-300">
              Eris Control Center
            </h1>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-400">
              Controlled chaos for beautiful screens
            </p>
          </div>
          <button
            onClick={handleLogout}
            className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-emerald-400/60 hover:text-emerald-200"
          >
            Logout
          </button>
        </div>
        <nav className="border-t border-slate-800/60 bg-slate-900/50">
          <div className="mx-auto flex max-w-6xl gap-4 px-6 py-3 text-sm font-medium uppercase tracking-[0.3em] text-slate-400">
            {navLinks.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-2 transition ${
                    isActive
                      ? 'bg-emerald-500/20 text-emerald-200'
                      : 'hover:bg-slate-800/80 hover:text-slate-200'
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
