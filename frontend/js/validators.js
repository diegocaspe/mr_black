/**
 * Reglas de validación del frontend. Replican `backend/app/core/validators.py` solo para dar
 * retroalimentación inmediata: el servidor SIEMPRE vuelve a validar y es la fuente de verdad.
 */
import { clearFieldError, setFieldError } from './ui.js';

const L = 'A-Za-zÁÉÍÓÚÜÑáéíóúüñ';
const PERSON_NAME = new RegExp(`^[${L}]+(?: [${L}]+)*$`);
const PRODUCT_NAME = new RegExp(`^[${L}0-9]+(?:[ .\\-][${L}0-9]+)*\\.?$`);
const HAS_LETTER = new RegExp(`[${L}]`);

export const collapse = (v) => String(v ?? '').normalize('NFC').replace(/\s+/g, ' ').trim();

export function normalizePhone(v) {
  const rawV = String(v ?? '').trim();
  if (!/^[\d\s\-().+]+$/.test(rawV)) return null;
  let d = rawV.replace(/\D/g, '');
  if (d.length === 11 && d.startsWith('51')) d = d.slice(2);
  return /^9\d{8}$/.test(d) ? d : null;
}

export function passwordScore(p) {
  let s = 0;
  if (p.length >= 8) s++;
  if (p.length >= 12) s++;
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) s++;
  if (/[^A-Za-z0-9]/.test(p)) s++;
  return s;
}
export const STRENGTH_LABEL = ['Muy débil', 'Débil', 'Aceptable', 'Buena', 'Fuerte'];

export const rules = {
  required: (msg = 'Este campo es obligatorio.') => (v) => (String(v ?? '').trim() ? null : msg),
  personName: (v) => {
    const s = collapse(v);
    if (!s) return 'El nombre es obligatorio.';
    if (s.length < 2 || s.length > 60) return 'El nombre debe tener entre 2 y 60 caracteres.';
    return PERSON_NAME.test(s) ? null : 'El nombre solo puede contener letras (incluidas tildes y ñ) y espacios.';
  },
  username: (v) => (/^[a-z0-9._-]{3,30}$/.test(String(v ?? '').trim().toLowerCase())
    ? null : 'Usuario inválido: 3 a 30 caracteres con letras, números, punto, guion o guion bajo, sin espacios.'),
  phone: (v) => (normalizePhone(v) ? null : 'El teléfono debe tener 9 dígitos y empezar con 9 (formato 9XXXXXXXX).'),
  optionalPhone: (v) => (!String(v ?? '').trim() ? null : rules.phone(v)),
  email: (v) => (/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(String(v ?? '').trim()) ? null : 'Ingresa un correo electrónico válido.'),
  optionalEmail: (v) => (!String(v ?? '').trim() ? null : rules.email(v)),
  password: (v) => {
    const p = String(v ?? '');
    if (p.length < 8) return 'La contraseña debe tener al menos 8 caracteres.';
    if (!new RegExp(`[${L}]`).test(p)) return 'La contraseña debe incluir al menos una letra.';
    if (!/\d/.test(p)) return 'La contraseña debe incluir al menos un número.';
    if (p.trim() !== p) return 'La contraseña no puede empezar ni terminar con espacios.';
    return null;
  },
  sameAs: (field, msg = 'Las contraseñas no coinciden.') => (v, form) => (v === form.elements[field]?.value ? null : msg),
  productName: (v) => {
    const s = collapse(v);
    if (s.length < 3 || s.length > 60) return 'El nombre debe tener entre 3 y 60 caracteres.';
    return PRODUCT_NAME.test(s) && HAS_LETTER.test(s) ? null : 'El nombre solo puede contener letras, números, espacios, guion y punto.';
  },
  price: (v) => {
    const s = String(v ?? '').trim();
    if (!/^\d+(\.\d{1,2})?$/.test(s)) return 'Ingresa un precio válido con máximo 2 decimales (ej. 25.90).';
    const n = Number(s);
    if (n < 0.1) return 'El precio mínimo es S/ 0.10.';
    if (n > 99999.99) return 'El precio máximo es S/ 99,999.99.';
    return null;
  },
  rating: (v) => {
    const s = String(v ?? '').trim();
    if (!/^\d(\.\d)?$/.test(s)) return 'La valoración debe tener un solo decimal (ej. 4.5).';
    const n = Number(s);
    return n >= 0 && n <= 5 ? null : 'La valoración debe estar entre 0.0 y 5.0.';
  },
  imageUrl: (v) => {
    const s = String(v ?? '').trim();
    if (!s) return null;
    if (s.length > 500) return 'La URL no puede superar 500 caracteres.';
    if (/^\/assets\/[A-Za-z0-9._/-]+$/.test(s) && !s.includes('..')) return null;
    try {
      const u = new URL(s);
      if (!['http:', 'https:'].includes(u.protocol) || /[\s<>"']/.test(s)) throw new Error();
      if (!u.hostname.includes('.') && u.hostname !== 'localhost') throw new Error();
      return null;
    } catch {
      return 'Ingresa una URL de imagen válida que empiece con http:// o https://.';
    }
  },
  intRange: (min, max, label = 'El valor') => (v) => {
    const s = String(v ?? '').trim();
    if (!/^\d+$/.test(s)) return `${label} debe ser un número entero.`;
    const n = Number(s);
    return n >= min && n <= max ? null : `${label} debe estar entre ${min} y ${max}.`;
  },
  reportDate: (v) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(v ?? ''))) return 'Ingresa una fecha válida.';
    return v >= '2000-01-01' && v <= '2099-12-31' ? null : 'La fecha debe estar entre 01/01/2000 y 31/12/2099.';
  },
  maxLen: (n) => (v) => (String(v ?? '').length <= n ? null : `Máximo ${n} caracteres.`),
};

/**
 * Valida un formulario con un mapa { nombreCampo: [regla, ...] }.
 * Muestra el primer error de cada campo y devuelve true si todo es válido.
 */
export function validateForm(form, schema) {
  let ok = true;
  let first = null;
  Object.entries(schema).forEach(([name, fns]) => {
    const input = form.elements[name];
    if (!input) return;
    clearFieldError(input);
    for (const fn of [].concat(fns)) {
      const msg = fn(input.value, form);
      if (msg) {
        setFieldError(form, name, msg);
        ok = false;
        first = first || input;
        break;
      }
    }
  });
  first?.focus();
  return ok;
}

/** Valida al salir de cada campo y limpia el error al corregir. */
export function liveValidate(form, schema) {
  Object.entries(schema).forEach(([name, fns]) => {
    const input = form.elements[name];
    if (!input) return;
    input.addEventListener('blur', () => {
      if (!input.value && !input.required) return;
      clearFieldError(input);
      for (const fn of [].concat(fns)) {
        const msg = fn(input.value, form);
        if (msg) { setFieldError(form, name, msg); break; }
      }
    });
    input.addEventListener('input', () => {
      if (input.getAttribute('aria-invalid') === 'true') clearFieldError(input);
    });
  });
}

/** Indicador de fortaleza de contraseña (0024792). */
export function attachStrengthMeter(input, meter, labelEl) {
  const update = () => {
    const score = input.value ? Math.max(1, passwordScore(input.value)) : 0;
    meter.dataset.score = String(score);
    if (labelEl) labelEl.textContent = input.value ? `Seguridad: ${STRENGTH_LABEL[score]}` : 'Mínimo 8 caracteres con letras y números.';
  };
  input.addEventListener('input', update);
  update();
}

/** Normaliza el teléfono al salir del campo (0024803): "987 654 321" → "987654321". */
export function attachPhoneNormalizer(input) {
  input.addEventListener('blur', () => {
    const n = normalizePhone(input.value);
    if (n) input.value = n;
  });
}
