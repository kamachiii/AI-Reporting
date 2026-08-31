import { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import LoginModal from './components/LoginModal';
import AdminLayout from './components/Admin/AdminLayout';
import UserWorkspace from './components/User/UserWorkspace';
import ErrorBoundary from './components/ErrorBoundary';
import toast, { Toaster } from 'react-hot-toast';

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    const userData = localStorage.getItem('user_data');
    if (token && userData) {
      try {
        setUser(JSON.parse(userData));
      } catch (e) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user_data');
      }
    }
    // Notifikasi sesi kadaluarsa (di-set oleh interceptor api.js)
    if (sessionStorage.getItem('session_expired')) {
      sessionStorage.removeItem('session_expired');
      toast('Sesi kamu sudah berakhir. Silakan login kembali.', { icon: '⏳' });
    }
    setLoading(false);
  }, []);

  const handleLogin = (userData) => {
    setUser(userData);
  };

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_data');
    setUser(null);
    toast('Anda telah logout.');
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center bg-canvas text-ink">Memuat aplikasi...</div>;
  return (
    <MotionConfig reducedMotion="user">
      <Toaster position="top-right" />
      {!user ? (
        <Routes>
          <Route path="*" element={
            <ErrorBoundary>
              <LoginModal onLoginSuccess={handleLogin} />
            </ErrorBoundary>
          } />
        </Routes>
      ) : user.role === 'admin' ? (
        <Routes>
          <Route path="/admin" element={<Navigate to="/admin/perusahaan-cabang" replace />} />
          <Route path="/" element={<Navigate to="/admin/perusahaan-cabang" replace />} />
          <Route path="/admin/:tabSlug" element={
            <ErrorBoundary>
              <AdminLayout user={user} onLogout={handleLogout} />
            </ErrorBoundary>
          } />
          <Route path="*" element={<Navigate to="/admin/perusahaan-cabang" replace />} />
        </Routes>
      ) : (
        <Routes>
          <Route path="*" element={
            <ErrorBoundary>
              <UserWorkspace user={user} onLogout={handleLogout} />
            </ErrorBoundary>
          } />
        </Routes>
      )}
    </MotionConfig>
  );
}


export default App;