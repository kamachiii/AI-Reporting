import { useState } from 'react';
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
      <div className="w-full max-w-md bg-white rounded-xl border border-hairline p-8 shadow-sm">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-4">
            <span className="text-2xl text-primary">✦</span>
          </div>
          <h1 className="font-serif text-2xl text-ink">DMS AI Platform</h1>
          <p className="text-muted text-sm mt-1">SaaS Add-on Chat AI untuk DMS</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-error text-sm">
            {error}
          </div>
        )}

        <form id="login-form" onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2 border border-hairline rounded-md focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary bg-canvas"
              placeholder="John Doe"
              disabled={isLoading}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2 border border-hairline rounded-md focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary bg-canvas"
              placeholder="••••••••"
              disabled={isLoading}
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 bg-primary text-white rounded-md font-medium hover:bg-primary-active transition-colors disabled:opacity-70 disabled:cursor-not-allowed"
          >
            {isLoading ? 'Memproses...' : 'Masuk ke Platform'}
          </button>
        </form>
      </div>
    </div>
  );
}