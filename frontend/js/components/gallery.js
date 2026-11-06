/**
 * Galería de fotos y gestor de fotos compartidos por las fichas de producto y de servicio.
 *
 * - `galleryView`: foto principal con flechas, contador y miniaturas.
 * - `photoManager`: rejilla de fotos subidas (mover al inicio / eliminar) y zona para agregar.
 * - `uploadPhotos`: reduce cada foto en el navegador y la sube como cuerpo binario.
 * El backend aplica los mismos límites y permisos (ADMIN y CAJA).
 */
import { api } from '../api.js';
import { html, raw, toast, toastError } from '../ui.js';

export const PHOTO_ROLES = ['ADMIN', 'CAJA'];
export const MAX_PHOTOS = 8;
const MAX_SIDE = 1600;
const ACCEPT = ['image/jpeg', 'image/png', 'image/webp'];

/**
 * Reduce la foto (lado mayor 1600 px) y la recodifica: menos peso y sin metadatos EXIF (p. ej. GPS).
 * Si el navegador no puede decodificarla, se envía tal cual y el servidor la valida.
 */
export async function prepareImage(file) {
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close?.();
    const type = file.type === 'image/png' ? 'image/png' : 'image/webp';
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, type, 0.86));
    if (blob && blob.type === type) return blob;
    return await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.86));
  } catch {
    return file;
  }
}

/** Foto principal + navegación. `images`: [{ src }]. Sin fotos muestra el ícono. */
export function galleryView({ images, active, alt, icon, badge = '' }) {
  const main = images[active];
  const many = images.length > 1;
  return html`<div class="pd-gallery">
    <div class="pd-main">
      ${main ? html`<img src="${main.src}" alt="${alt}${many ? ` — foto ${active + 1} de ${images.length}` : ''}">`
        : html`<i class="fa-solid ${icon}" aria-hidden="true"></i>`}
      ${badge ? html`<span class="product-cat">${badge}</span>` : ''}
      ${many ? html`
        <button type="button" class="pd-nav prev" data-step="-1" aria-label="Foto anterior"><i class="fa-solid fa-chevron-left" aria-hidden="true"></i></button>
        <button type="button" class="pd-nav next" data-step="1" aria-label="Foto siguiente"><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
        <span class="pd-count" aria-hidden="true">${active + 1} / ${images.length}</span>` : ''}
    </div>
    ${many ? html`<div class="pd-thumbs" role="group" aria-label="Fotos">${images.map((img, i) => html`
      <button type="button" class="pd-thumb" data-thumb="${i}" aria-label="Ver foto ${i + 1}" aria-pressed="${i === active}">
        <img src="${img.src}" alt="" loading="lazy"></button>`)}</div>` : ''}
  </div>`;
}

/** Rejilla de fotos subidas y zona para agregar. `coverIsUpload`: la primera subida es la portada. */
export function photoManager({ uploads, coverIsUpload, uploading }) {
  const left = MAX_PHOTOS - uploads.length;
  return html`<div class="pd-photos" role="list" aria-label="Fotos subidas">
      ${uploads.map((img, i) => html`<div class="pd-photo" role="listitem">
        <img src="${img.url}" alt="Foto ${i + 1}" loading="lazy">
        ${i === 0 && coverIsUpload ? html`<span class="pd-photo-tag">Portada</span>` : ''}
        <div class="pd-photo-actions">
          ${i > 0 ? html`<button type="button" class="icon-btn" data-first="${img.id}" aria-label="Mover la foto ${i + 1} al inicio" title="Mover al inicio"><i class="fa-solid fa-arrow-up-wide-short" aria-hidden="true"></i></button>` : ''}
          <button type="button" class="icon-btn" data-del-photo="${img.id}" aria-label="Eliminar la foto ${i + 1}" title="Eliminar"><i class="fa-solid fa-trash" aria-hidden="true"></i></button>
        </div>
      </div>`)}
      ${left > 0 ? html`<label class="pd-drop" data-drop>
        <input type="file" accept="${ACCEPT.join(',')}" multiple class="sr-only" data-file ${uploading ? raw('disabled') : ''}>
        ${uploading ? html`<span class="spinner" aria-hidden="true"></span><span class="xs">${uploading}</span>`
          : html`<i class="fa-solid fa-plus" aria-hidden="true"></i><span class="xs">Agregar fotos</span>`}
      </label>` : ''}
    </div>
    <p class="field-hint mt-2">JPG, PNG o WebP · hasta ${MAX_PHOTOS} fotos (quedan ${left}). Puedes arrastrarlas aquí. Se optimizan automáticamente antes de subirlas.</p>`;
}

/** Conecta el selector de archivos y el arrastrar-y-soltar del gestor. */
export function bindPhotoInput(root, { busy, onFiles }) {
  const input = root.querySelector('[data-file]');
  input?.addEventListener('change', () => { if (input.files.length) onFiles(input.files); });
  const drop = root.querySelector('[data-drop]');
  if (!drop) return;
  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('is-over'); }));
  ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, () => drop.classList.remove('is-over')));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    if (!busy() && e.dataTransfer?.files?.length) onFiles(e.dataTransfer.files);
  });
}

/**
 * Sube las fotos una a una. Devuelve { owner, done }: `owner` es la última respuesta del servidor
 * (el producto o servicio con su galería actualizada).
 */
export async function uploadPhotos(files, { current, url, onProgress }) {
  const list = [...files];
  const valid = list.filter((f) => ACCEPT.includes(f.type));
  if (valid.length < list.length) toast('Algunos archivos no son JPG, PNG o WebP y se omitieron.', 'err');
  const room = MAX_PHOTOS - current;
  if (valid.length > room) toast(`Solo se pueden agregar ${room} foto(s) más.`, 'info');
  const batch = valid.slice(0, Math.max(0, room));
  let owner = null;
  let done = 0;
  for (const file of batch) {
    onProgress(`Subiendo ${done + 1} de ${batch.length}…`);
    try {
      owner = await api.upload(url, await prepareImage(file));
      done += 1;
    } catch (err) {
      toastError(err);
      break;
    }
  }
  if (done) toast(done === 1 ? 'Foto agregada.' : `${done} fotos agregadas.`);
  return { owner, done };
}

/** Índice siguiente/anterior con vuelta al inicio. */
export const stepIndex = (active, delta, n) => (active + delta + n) % n;
