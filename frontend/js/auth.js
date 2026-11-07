/** Páginas de autenticación: login, registro, recuperación y restablecimiento de contraseña. */
import { api, currentUser } from './api.js';
import { $, submitWith, toast, formValues } from './ui.js';
import {
  attachPhoneNormalizer, attachStrengthMeter, liveValidate, normalizePhone, rules, validateForm,
} from './validators.js';

/** Solo permite redirecciones internas (evita open redirect). */
function safeNext() {
  const next = new URLSearchParams(location.search).get('next');
  return next && next.startsWith('/') && !next.startsWith('//') && !next.includes('\\') ? next : null;
}

function homeFor(user) {
  return user.role === 'CLIENTE' ? '/app.html#/mis-citas' : '/app.html';
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-toggle-password]');
  if (!btn) return;
  const input = document.getElementById(btn.dataset.togglePassword);
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.setAttribute('aria-label', show ? 'Ocultar contraseña' : 'Mostrar contraseña');
  btn.querySelector('i').className = `fa-solid ${show ? 'fa-eye-slash' : 'fa-eye'}`;
});

/* ------------------------------------------------------------------ login (0024799, 0024819) */
const loginForm = $('#login-form');
if (loginForm) {
  currentUser().then((u) => { if (u) location.replace(safeNext() || homeFor(u)); }).catch(() => {});
  const schema = {
    identifier: [rules.required('Ingresa tu usuario, teléfono o correo.')],
    password: [rules.required('Ingresa tu contraseña.')],
  };
  liveValidate(loginForm, schema);
  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(loginForm, schema)) return;
    const data = formValues(loginForm);
    try {
      const user = await submitWith(loginForm, loginForm.querySelector('[type=submit]'),
        () => api.post('/auth/login', { identifier: data.identifier.trim(), password: data.password }));
      location.replace(safeNext() || homeFor(user));
    } catch {
      loginForm.elements.password.value = '';
    }
  });
}

/* ------------------------------------------------------------------ registro (0024792, 0024803) */
const registerForm = $('#register-form');
if (registerForm) {
  const schema = {
    full_name: [rules.personName],
    phone: [rules.phone],
    email: [rules.email],
    password: [rules.password, (v, f) => {
      const p = normalizePhone(f.elements.phone.value);
      return p && v.includes(p) ? 'La contraseña no debe contener tu número de teléfono.' : null;
    }],
    password_confirm: [rules.required('Confirma tu contraseña.'), rules.sameAs('password')],
  };
  liveValidate(registerForm, schema);
  attachPhoneNormalizer(registerForm.elements.phone);
  attachStrengthMeter(registerForm.elements.password, $('#strength'), $('#strength-label'));
  registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(registerForm, schema)) return;
    const d = formValues(registerForm);
    try {
      await submitWith(registerForm, registerForm.querySelector('[type=submit]'), () => api.post('/auth/register', {
        full_name: d.full_name, phone: d.phone, email: d.email.trim(), password: d.password, password_confirm: d.password_confirm,
      }));
      toast('Cuenta creada correctamente. ¡Bienvenido a Mr Black!');
      location.replace(safeNext() || '/index.html');
    } catch { /* errores mostrados por campo */ }
  });
}

/* ------------------------------------------------------------------ recuperación */
const forgotForm = $('#forgot-form');
if (forgotForm) {
  const schema = { email: [rules.email] };
  liveValidate(forgotForm, schema);
  forgotForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(forgotForm, schema)) return;
    try {
      await submitWith(forgotForm, forgotForm.querySelector('[type=submit]'),
        () => api.post('/auth/forgot-password', { email: forgotForm.elements.email.value.trim() }));
      $('#forgot-done').hidden = false;
      forgotForm.hidden = true;
    } catch { /* mostrado en el formulario */ }
  });
}

/* ------------------------------------------------------------------ restablecer */
const resetForm = $('#reset-form');
if (resetForm) {
  const token = new URLSearchParams(location.search).get('token') || '';
  // No dejar el token en el historial ni en la barra de direcciones.
  history.replaceState(null, '', location.pathname);
  const invalid = () => { $('#reset-invalid').hidden = false; resetForm.hidden = true; };
  if (token.length < 20) invalid();
  else {
    api.get(`/auth/reset-password/${encodeURIComponent(token)}`).then(() => { resetForm.hidden = false; resetForm.elements.password.focus(); })
      .catch(invalid);
  }
  const schema = {
    password: [rules.password],
    password_confirm: [rules.required('Confirma tu contraseña.'), rules.sameAs('password')],
  };
  liveValidate(resetForm, schema);
  attachStrengthMeter(resetForm.elements.password, $('#strength'), $('#strength-label'));
  resetForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(resetForm, schema)) return;
    const d = formValues(resetForm);
    try {
      await submitWith(resetForm, resetForm.querySelector('[type=submit]'),
        () => api.post('/auth/reset-password', { token, password: d.password, password_confirm: d.password_confirm }));
      toast('Contraseña actualizada. Ya puedes iniciar sesión.');
      setTimeout(() => location.replace('/login.html'), 1200);
    } catch (err) {
      if (err.code === 'invalid_token') invalid();
    }
  });
}
