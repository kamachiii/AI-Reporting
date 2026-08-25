import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, X } from 'lucide-react';

export default function ModelPickerModal({ isOpen, onClose, onSelect, models }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All');

  // Ambil daftar provider unik untuk filter kategori
  const uniqueProviders = useMemo(() => {
    const providers = models.map(m => m.provider);
    return ['All', ...new Set(providers)];
  }, [models]);

  // Filter model berdasarkan kategori dan pencarian
  const filteredModels = useMemo(() => {
    return models.filter(m => {
      const matchCategory = selectedCategory === 'All' || m.provider === selectedCategory;
      const matchSearch = m.label.toLowerCase().includes(searchTerm.toLowerCase());
      return matchCategory && matchSearch;
    });
  }, [models, searchTerm, selectedCategory]);

  const handleSelect = (modelId) => {
    onSelect(modelId);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div 
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      >
        <motion.div 
          initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
          transition={{ type: 'spring', damping: 20, stiffness: 300 }}
          className="bg-white rounded-xl max-w-2xl w-full h-[530px] shadow-xl border border-hairline flex flex-col overflow-hidden scrollbar-thin scrollbar-thumb-primary-active"
        >
          {/* HEADER */}
          <div className="flex items-center justify-between p-4 border-b border-hairline gap-4">
            <h2 className="font-serif text-lg text-ink min-w-[100px]">Pilih Model AI</h2>
            
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
              <input
                type="text"
                placeholder="Cari nama model..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>

            <button onClick={onClose} className="text-muted hover:text-ink transition-colors min-w-[30px] flex justify-end">
              <X size={24} />
            </button>
          </div>

          {/* BODY */}
          <div className="flex-1 overflow-y-auto p-4">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 items-stretch">
              {filteredModels.length === 0 ? (
                <div className="col-span-full py-8 text-center text-muted">
                  Tidak ada model yang ditemukan.
                </div>
              ) : (
                filteredModels.map((model) => (
                  <button
                    key={model.id}
                    onClick={() => handleSelect(model.id)}
                    className="w-full min-w-0 max-w-full h-[120px] overflow-hidden bg-white rounded-xl border border-hairline p-4 flex flex-col items-center justify-center text-center hover:shadow-md hover:border-primary transition-all cursor-pointer"
                  >
                    {/* LOGO PROVIDER */}
                    <div className="w-12 h-12 mb-3 rounded-full bg-surface-soft flex items-center justify-center text-muted overflow-hidden flex-shrink-0">
                      {/* 
                        ==============================================================
                        KOMENTAR: GANTI BAGIAN INI DENGAN TAG <img> ASLI ANDA
                        ==============================================================
                        <img src="https://url_logo_deepseek.png" className="w-full h-full object-cover" />
                      */}
                      <span className="text-xs font-bold">
                        {model.provider.substring(0, 2).toUpperCase()}
                      </span>
                    </div>
                    <p className="text-sm font-medium text-ink break-words text-balance leading-snug w-full">
                      {model.label}
                    </p>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* FOOTER */}
          <div className="border-t border-hairline p-3 bg-white sticky bottom-0 flex flex-wrap gap-2 justify-center">
            {uniqueProviders.map((provider) => (
              <button
                key={provider}
                type='button'
                onClick={() => setSelectedCategory(provider)}
                className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                  selectedCategory === provider
                    ? 'bg-primary text-white'
                    : 'bg-surface-soft text-ink hover:bg-hairline'
                }`}
              >
                {provider}
              </button>
            ))}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}