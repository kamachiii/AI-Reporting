import { useState, useEffect } from 'react';
import LoginModal from './components/LoginModal';
import AdminLayout from './components/Admin/AdminLayout';
import toast, { Toaster } from 'react-hot-toast';

// Placeholder untuk User Workspace (nanti kita isi)
const UserWorkspace = ({ user, onLogout }) => (
  <div className="min-h-screen bg-canvas p-8">
    <div className="max-w-4xl mx-auto bg-white rounded-xl border border-hairline p-6">
      <div className="flex justify-between items-center mb-4">
        <h1 className="font-serif text-xl text-ink">User Workspace</h1>
        <button onClick={onLogout} className="px-4 py-1.5 border border-hairline rounded-md text-sm hover:bg-surface-soft transition-colors">Logout</button>
      </div>
      <p className="text-body">Halo, <strong>{user.username}</strong>! (Role: {user.role})</p>
      <p className="text-muted text-sm mt-2">Akses cabang: {user.allowed_branches.join(', ')}</p>
      <p className="text-muted text-sm mt-4">(User Workspace sedang dibangun)</p>
    </div>
  </div>
);

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
    <>
      <Toaster position="top-right" />
      {!user ? (
        <LoginModal onLoginSuccess={handleLogin} />
      ) : user.role === 'admin' ? (
        <AdminLayout user={user} onLogout={handleLogout} />
      ) : (
        <UserWorkspace user={user} onLogout={handleLogout} />
      )}
    </>
  );
}


export default App;