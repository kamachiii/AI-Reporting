import { useEffect, useState } from 'react';

/**
 * Menunda propagasi nilai (untuk search input) agar filter
 * tidak dijalankan pada setiap ketikan. Default 300ms.
 */
export default function useDebounce(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
