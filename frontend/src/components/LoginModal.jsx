import { useState } from 'react';
import { Bot } from 'lucide-react';
import { api } from '../services/api';
import { notify } from '../utils/notification';

export default function LoginModal({ onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const data = await api.login(username, password);
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('user_data', JSON.stringify(data));
      notify.success(`Selamat datang, ${data.username}!`);
      onLoginSuccess(data);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Login gagal. Periksa username & password.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-md bg-surface-card rounded-xl border border-hairline p-8 shadow-xs space-y-6">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-primary/10 text-primary mb-4 border border-primary/20 shadow-2xs">
            <Bot className="w-6 h-6 text-primary" />
          </div>
          <h1 className="font-serif text-3xl text-ink font-normal tracking-tight">
            DMS AI Platform
          </h1>
          <p className="text-muted text-xs mt-1.5 font-sans">
            Asisten Laporan Dealer
          </p>
        </div>

        {error && (
          <div className="p-3 bg-red-50/80 border border-error/20 rounded-md text-error text-xs leading-relaxed">
            {error}
          </div>
        )}

        <form id="login-form" onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-body-strong mb-1.5">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full h-10 px-3.5 text-sm bg-canvas border border-hairline rounded-md text-ink placeholder:text-muted/60 focus:outline-none focus:border-primary focus:ring-3 focus:ring-primary/15 transition-all font-sans"
              placeholder="Masukkan username Anda…"
              disabled={isLoading}
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-body-strong mb-1.5">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full h-10 px-3.5 text-sm bg-canvas border border-hairline rounded-md text-ink placeholder:text-muted/60 focus:outline-none focus:border-primary focus:ring-3 focus:ring-primary/15 transition-all font-sans"
              placeholder="••••••••"
              disabled={isLoading}
              required
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full h-10 px-5 bg-primary hover:bg-primary-active text-on-primary rounded-md text-sm font-medium transition-colors shadow-2xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed mt-2"
          >
            {isLoading ? 'Memvalidasi Kredensial…' : 'Masuk ke Platform'}
          </button>
        </form>
      </div>
    </div>
  );
}