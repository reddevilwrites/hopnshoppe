const API_BASE = import.meta.env.VITE_API_BASE || '/api';
const API_ROOT = import.meta.env.VITE_API_ROOT || (API_BASE === '/api' ? '' : API_BASE.replace(/\/api$/, ''));

export { API_BASE, API_ROOT };
