import toast from 'react-hot-toast';

// Wrapper untuk memastikan semua toast punya gaya yang sama (durasi, posisi)
const defaultOptions = {
  duration: 4000,
  position: 'top-right',
};

export const notify = {
  /**
   * Menampilkan notifikasi sukses.
   * @param {string} message - Pesan yang akan ditampilkan.
   * @param {object} options - Opsi tambahan (durasi, undo, dll).
   */
  success: (message, options = {}) => {
    toast.success(message, { ...defaultOptions, ...options });
  },

  /**
   * Menampilkan notifikasi error.
   * @param {string} message - Pesan error.
   * @param {object} options - Opsi tambahan.
   */
  error: (message, options = {}) => {
    toast.error(message, { ...defaultOptions, ...options });
  },

  /**
   * Menampilkan notifikasi loading (untuk proses async).
   */
  promise: (promise, messages, options = {}) => {
    return toast.promise(promise, messages, { ...defaultOptions, ...options });
  },

  /**
   * Menampilkan notifikasi biasa (info/neutral).
   */
  info: (message, options = {}) => {
    toast(message, { ...defaultOptions, ...options });
  },

  /**
   * Membatalkan semua toast yang sedang tampil.
   */
  dismiss: () => {
    toast.dismiss();
  },
};