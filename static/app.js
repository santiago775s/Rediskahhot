const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const letra = (i) => String.fromCharCode(65 + i);

const token = sessionStorage.token || (sessionStorage.token = crypto.randomUUID());

async function api(url, { method = "GET", body } = {}) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body) });
  const datos = await r.json();
  datos._ok = r.ok;
  return datos;
}

function terminal(id, comando, ...respuestas) {
  const t = $(id);
  const bloque = document.createElement("div");
  bloque.innerHTML = (comando ? `<span class="prompt">&gt;</span> ${esc(comando)}` : "")
                   + respuestas.map((r) => `<span class="resp">${esc(r)}</span>`).join("");
  t.append(bloque);
  while (t.children.length > 14) t.firstChild.remove();
  t.scrollTop = t.scrollHeight;
}

function volcar(id, comandos = []) {
  comandos.forEach(([cmd, resp]) => terminal(id, cmd, resp));
}

function temporizador(elTexto, elBarra, { duracion = 30, onFin } = {}) {
  let fin = 0, activo = false, avisado = false;
  const pintar = () => {
    const s = activo ? Math.max(0, Math.ceil((fin - Date.now()) / 1000)) : 0;
    elTexto.textContent = activo ? s : "--";
    elBarra.style.width = activo ? `${Math.min(100, (s / duracion) * 100)}%` : "0%";
    if (activo && s === 0 && !avisado) { avisado = true; onFin && onFin(); }
  };
  setInterval(pintar, 200);
  return {
    sincronizar(segundos) { fin = Date.now() + segundos * 1000; activo = true; avisado = false; pintar(); },
    detener() { activo = false; pintar(); },
  };
}

function grafico(el, opciones, votos, correcta) {
  const total = votos.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...votos);
  el.innerHTML = opciones.map((o, i) => {
    const pct = total ? Math.round((votos[i] / total) * 100) : 0;
    return `<div class="barra-fila ${i === correcta ? "correcta" : ""}">
      <span class="barra-nombre">${letra(i)} · ${esc(o)}</span>
      <div class="barra-pista"><i style="width:${(votos[i] / max) * 100}%"></i></div>
      <b>${votos[i]} · ${pct}%</b>
    </div>`;
  }).join("") + `<p class="total">${total} voto${total === 1 ? "" : "s"}</p>`;
}

function listaRanking(el, ranking) {
  el.innerHTML = ranking.length
    ? ranking.map((r) => `<li><span>${esc(r.nombre)}</span><b>${r.puntos} pts</b></li>`).join("")
    : '<li class="vacio">Nadie tiene puntos todavía</li>';
}

function conectar(termId, chipId, { onPregunta, onCierre, onAbrir }) {
  terminal(termId, "SUBSCRIBE votacion:sala1", '1) "subscribe"', '2) "votacion:sala1"', "3) (integer) 1");
  const es = new EventSource("/api/stream");
  es.onopen = () => { $(chipId).textContent = "● suscrito a votacion:sala1"; onAbrir && onAbrir(); };
  es.onerror = () => { $(chipId).textContent = "● reconectando…"; };
  es.addEventListener("votacion:sala1", (e) => {
    const m = JSON.parse(e.data);
    const corto = e.data.length > 140 ? e.data.slice(0, 140) + "…" : e.data;
    terminal(termId, null, '1) "message"', '2) "votacion:sala1"', `3) ${corto}`);
    (m.tipo === "pregunta" ? onPregunta : onCierre)(m);
  });
}
