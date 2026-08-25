import { Component } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

/**
 * Penahan crash global: jika satu komponen meledak (referensi undefined,
 * data tak terduga, dsb.), SELURUH halaman tidak ikut putih — cukup
 * kartu error dengan pesan + opsi coba lagi / muat ulang.
 *
 * Pemakaian: bungkus subtree yang ingin dilindungi,
 * mis. <ErrorBoundary><AdminLayout/></ErrorBoundary>.
 */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    // Tersedia di DevTools console untuk debugging
    console.error('[ErrorBoundary]', error, errorInfo);
  }

  handleReset = () => {
    // Coba render ulang subtree tanpa reload penuh
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const message = String(this.state.error?.message || this.state.error || 'Unknown error');
      return (
        <div className="min-h-screen bg-canvas flex items-center justify-center p-6">
          <div className="bg-white rounded-xl border border-hairline shadow-sm max-w-md w-full p-8">
            <div className="flex items-center gap-3 mb-4">
              <span className="w-10 h-10 rounded-full bg-error/10 text-error flex items-center justify-center shrink-0">
                <AlertTriangle size={20} />
              </span>
              <h1 className="font-serif text-lg text-ink leading-snug">
                Terjadi kesalahan tak terduga
              </h1>
            </div>
            <p className="text-muted text-sm mb-4">
              Bagian aplikasi gagal dirender. Detail kesalahan (untuk pelaporan/debug):
            </p>
            <pre className="text-xs bg-surface-soft rounded-md p-3 overflow-x-auto text-body whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
              {message}
            </pre>
            <div className="flex gap-2 mt-6">
              <button
                onClick={this.handleReset}
                className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft transition-colors"
              >
                Coba Lagi
              </button>
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active transition-colors flex items-center gap-2"
              >
                <RefreshCw size={14} /> Muat Ulang Halaman
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
