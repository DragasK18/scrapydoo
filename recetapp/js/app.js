// RecetApp: carga data/precios.csv en el navegador y pinta el buscador y filtros.
// Todo el contenido del CSV se pinta con textContent, nunca con innerHTML.

import { parsearCSV } from "./csv.js";
import {
  MIN_CARACTERES,
  buscar,
  claveFilaConsciente,
  construirMatrizComparativa,
  extraerOpcionesFiltros,
  idProductoCarrito,
  masBaratoQue,
  normalizar,
  preparar,
  rangoFechas,
} from "./buscar.js";

const RUTA_DATOS = "data/precios.csv";
const ESPERA_MS = 150;
const GRUPOS_POR_PAGINA = 25;

const pesos = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
const porcentaje = new Intl.NumberFormat("es-CO", { style: "percent", maximumFractionDigits: 1 });
const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];

const $ = (id) => document.getElementById(id);
const entrada = $("consulta");
const selectPrincipio = $("filtro-principio");
const selectMarca = $("filtro-marca");
const selectOrden = $("filtro-orden");
const checkEquivalentes = $("incluir-equivalentes");
const btnLimpiar = $("limpiar-todo");
const btnVistaCuadricula = $("vista-cuadricula");
const btnVistaLista = $("vista-lista");

const estado = $("estado");
const inicio = $("inicio");
const resultados = $("resultados");
const panel = $("panel");
const panelContenido = $("panel-contenido");
const kpiPanel = $("kpi-panel");

let productos = [];
let tarjetaElegida = null;
let farmaciaSeleccionada = "";
let modoVista = "cuadricula"; // "cuadricula" | "lista"

const barraCarrito = $("barra-carrito");
const carritoContador = $("carrito-contador");
const carritoGrupos = $("carrito-grupos");
const btnVaciarCarrito = $("btn-vaciar-carrito");
const btnExportarCarrito = $("btn-exportar-carrito");

let carrito = new Map(); // idProductoCarrito(p) -> objeto producto

function fechaLarga(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  return `${d} de ${MESES[m - 1]} de ${a}`;
}

function el(etiqueta, clase, texto) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== undefined) nodo.textContent = texto;
  return nodo;
}

function plural(n, uno, varios) {
  return `${n.toLocaleString("es-CO")} ${n === 1 ? uno : varios}`;
}

function tarjeta({ producto: p, coincide, masBarata }, marcarCoincidencias) {
  const li = el("li");
  const art = el("article", "tarjeta" + (masBarata ? " mas-barata" : ""));

  const cabecera = el("div", "tarjeta-cabecera");
  cabecera.append(el("h3", "farmacia", p.farmacia));

  const etiquetas = el("div", "etiquetas");
  if (masBarata) etiquetas.append(el("span", "etiqueta barata", "Más barata por unidad"));
  if (p.descuentoPct >= 5) {
    etiquetas.append(el("span", "etiqueta descuento", `-${Math.round(p.descuentoPct)}%`));
  }
  if (coincide && marcarCoincidencias) etiquetas.append(el("span", "etiqueta coincide", "Coincide"));
  if (p.precioUnidadNum === null) etiquetas.append(el("span", "etiqueta sin-unidad", "Sin precio/und"));
  if (etiquetas.childElementCount) cabecera.append(etiquetas);
  art.append(cabecera);

  const cuerpo = el("div", "tarjeta-cuerpo");
  cuerpo.append(el("p", "producto", p.producto));

  const datos = el("dl", "datos");
  const filas = [
    ["Marca", p.marca],
    ["Presentación", p.presentacion],
    ["Código", p.codigo],
  ];
  for (const [nombre, valor] of filas) {
    datos.append(el("dt", "", nombre), el("dd", "", valor || "—"));
  }
  cuerpo.append(datos);
  art.append(cuerpo);

  const bloquePrecios = el("div", "tarjeta-precios");
  const precioPrincipal = el("p", "precio-principal");
  if (p.precioNum !== null) {
    precioPrincipal.append(pesos.format(p.precioNum));
    if (p.precioListaNum && p.precioListaNum > p.precioNum) {
      precioPrincipal.append(el("span", "precio-lista-tachado", ` ${pesos.format(p.precioListaNum)}`));
    }
    if (p.precioUnidadNum !== null) {
      precioPrincipal.append(el("small", "", ` (${pesos.format(p.precioUnidadNum)} c/u)`));
    }
  } else {
    precioPrincipal.append(el("small", "", "Precio no disponible"));
  }
  bloquePrecios.append(precioPrincipal);

  const idProd = idProductoCarrito(p);
  const estaEnCarrito = carrito.has(idProd);
  if (estaEnCarrito) art.classList.add("en-carrito");

  const acciones = el("div", "acciones");

  const btnAgrupar = el(
    "button",
    "btn-agrupar" + (estaEnCarrito ? " activo" : ""),
    estaEnCarrito ? "✓ Agrupado" : "+ Agrupar"
  );
  btnAgrupar.type = "button";
  btnAgrupar.addEventListener("click", (e) => {
    e.stopPropagation();
    alternarProductoCarrito(p, art, btnAgrupar);
  });
  acciones.append(btnAgrupar);

  const comparar = el("button", "comparar", "Comparar ahorro");
  comparar.type = "button";
  acciones.append(comparar);
  if (/^https?:\/\//.test(p.url)) acciones.append(enlaceFarmacia(p));
  bloquePrecios.append(acciones);

  art.append(bloquePrecios);

  art.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    abrirPanel(p, art);
  });

  li.append(art);
  return li;
}

function enlaceFarmacia(p) {
  const a = el("a", "enlace", `Ver en ${p.farmacia} ↗`);
  a.href = p.url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function fechaTexto(fecha) {
  return /^\d{4}-\d{2}-\d{2}$/.test(fecha) ? fechaLarga(fecha) : fecha;
}

function resumenProducto(p, clase) {
  const caja = el("div", clase);
  caja.append(el("p", "resumen-farmacia", `${p.farmacia} · ${p.marca || "sin marca"}`));
  caja.append(el("p", "resumen-producto", p.producto));

  const precioInfo = el("p", "resumen-precio");
  precioInfo.append(pesos.format(p.precioNum));
  if (p.precioUnidadNum !== null) {
    precioInfo.append(el("small", "", ` (${pesos.format(p.precioUnidadNum)} c/u)`));
  }
  caja.append(precioInfo);

  caja.append(el("p", "resumen-detalle", `${p.presentacion} · ${fechaTexto(p.fecha)}`));
  return caja;
}

function contenidoPanel(p) {
  const r = masBaratoQue(productos, p);
  const nodos = [];
  const grupoTexto = `${p.principio_activo} ${p.concentracion}`.trim();

  if (r.tipo === "sin-unidades") {
    nodos.push(el("p", "panel-elegido", `${p.producto} · ${p.farmacia}`));
    nodos.push(
      el(
        "p",
        "panel-nota",
        "Este producto no informa cuántas unidades trae, así que no se puede calcular su precio por unidad " +
          "ni compararlo con otros. Revisa la presentación en la farmacia."
      )
    );
    return nodos;
  }

  if (r.tipo === "es-la-mas-barata") {
    nodos.push(
      el(
        "p",
        "panel-ok",
        r.unico
          ? `Es el único producto de ${grupoTexto} con precio en nuestros datos.`
          : `Ya es la opción más barata por unidad de ${grupoTexto} en nuestros datos.`
      )
    );
    nodos.push(resumenProducto(p, "resumen"));
    return nodos;
  }

  const { mejor, unidades } = r;
  nodos.push(el("p", "panel-intro", `Con ${grupoTexto}, lo más barato por unidad es:`));
  nodos.push(resumenProducto(mejor, "resumen mejor"));

  const ahorro = el("div", "ahorro");
  const titular = el("p", "ahorro-titular");
  titular.append(
    el("strong", "", `Ahorras ${porcentaje.format(r.porcentaje / 100)}`),
    ` por unidad (${pesos.format(r.ahorroUnidad)} menos cada una).`
  );
  ahorro.append(titular);
  ahorro.append(
    el(
      "p",
      "ahorro-total",
      `Por ${unidades} unidades, como trae tu elección: ${pesos.format(r.costoElegido)} frente a unos ` +
        `${pesos.format(r.costoMejor)}. Son ${pesos.format(r.ahorroTotal)} menos.`
    )
  );
  nodos.push(ahorro);

  if (/^https?:\/\//.test(mejor.url)) nodos.push(enlaceFarmacia(mejor));

  nodos.push(el("p", "panel-comparado", `Comparado con: ${p.producto} · ${p.farmacia} · ${pesos.format(p.precioNum)}`));
  nodos.push(
    el(
      "p",
      "panel-nota",
      "Mismo principio activo y concentración; la forma (tableta, cápsula) o la marca pueden cambiar. " +
        "Antes de cambiar, consulta con tu médico o farmacéutico."
    )
  );
  return nodos;
}

function abrirPanel(p, art) {
  tarjetaElegida?.classList.remove("elegida");
  tarjetaElegida = art;
  art.classList.add("elegida");
  panelContenido.replaceChildren(...contenidoPanel(p));
  panel.hidden = false;
  panel.scrollTop = 0;
  $("panel-titulo").focus();
}

function cerrarPanel(devolverFoco = false) {
  if (panel.hidden) return;
  panel.hidden = true;
  tarjetaElegida?.classList.remove("elegida");
  if (devolverFoco) tarjetaElegida?.querySelector(".comparar")?.focus();
  tarjetaElegida = null;
}

function grupo(g) {
  const seccion = el("section", "grupo");
  const partesTitulo = [g.principio];
  if (g.concentracion && g.concentracion !== "N/A") partesTitulo.push(g.concentracion);
  if (g.unidades) partesTitulo.push(`X ${g.unidades} UND`);
  const tituloTexto = partesTitulo.join(" · ");
  const cabeceraGrupo = el("div", "grupo-cabecera");
  cabeceraGrupo.append(el("h2", "grupo-titulo", tituloTexto));

  const derechaGrupo = el("div", "grupo-cabecera-derecha");
  const desde = g.minimo !== null ? ` · desde ${pesos.format(g.minimo)} por unidad` : "";
  derechaGrupo.append(el("p", "grupo-meta", plural(g.items.length, "opción", "opciones") + desde));

  const todosEnCarrito = g.items.every((it) => carrito.has(idProductoCarrito(it.producto)));
  const btnGrupo = el(
    "button",
    "btn-agrupar-grupo",
    todosEnCarrito ? "Quitar grupo" : "+ Agrupar grupo"
  );
  btnGrupo.type = "button";
  btnGrupo.addEventListener("click", () => {
    const yaEstanTodos = g.items.every((it) => carrito.has(idProductoCarrito(it.producto)));
    for (const it of g.items) {
      const id = idProductoCarrito(it.producto);
      if (yaEstanTodos) carrito.delete(id);
      else carrito.set(id, it.producto);
    }
    actualizarBarraCarrito();
    pintar();
  });
  derechaGrupo.append(btnGrupo);

  cabeceraGrupo.append(derechaGrupo);
  seccion.append(cabeceraGrupo);

  const marcar = g.coincidencias < g.items.length;
  const lista = el("ol", "tarjetas" + (modoVista === "lista" ? " vista-lista" : ""));
  for (const item of g.items) lista.append(tarjeta(item, marcar));
  seccion.append(lista);
  return seccion;
}

// KPIs interactivos: hacen clic para filtrar por esa farmacia
function mostrarKPIs(listaProductos) {
  kpiPanel.replaceChildren();

  const total = listaProductos.length;
  const conteo = {};
  for (const p of listaProductos) {
    conteo[p.farmacia] = (conteo[p.farmacia] || 0) + 1;
  }

  const crearBotonKPI = (etiqueta, valor, claveFarmacia) => {
    const activa = farmaciaSeleccionada === claveFarmacia;
    const btn = el("button", "kpi-caja" + (activa ? " kpi-destacado" : ""));
    btn.type = "button";
    btn.dataset.farmacia = claveFarmacia;
    btn.setAttribute("aria-pressed", String(activa));
    btn.append(
      el("span", "kpi-etiqueta", etiqueta),
      el("strong", "kpi-valor", valor.toLocaleString("es-CO"))
    );
    btn.addEventListener("click", () => {
      farmaciaSeleccionada = farmaciaSeleccionada === claveFarmacia ? "" : claveFarmacia;
      actualizarEstadoKPIs();
      pintar();
    });
    return btn;
  };

  kpiPanel.append(crearBotonKPI("Total Base de Datos", total, ""));

  const farmaciasOrdenadas = Object.entries(conteo).sort((a, b) => b[1] - a[1]);
  for (const [farmacia, cantidad] of farmaciasOrdenadas) {
    kpiPanel.append(crearBotonKPI(farmacia, cantidad, farmacia));
  }
}

function actualizarEstadoKPIs() {
  for (const btn of kpiPanel.querySelectorAll(".kpi-caja")) {
    const activa = btn.dataset.farmacia === farmaciaSeleccionada;
    btn.classList.toggle("kpi-destacado", activa);
    btn.setAttribute("aria-pressed", String(activa));
  }
}

function poblarSelectores(listaProductos) {
  const { principios, marcas } = extraerOpcionesFiltros(listaProductos);

  for (const { nombre, total } of principios) {
    const opt = el("option", "", `${nombre} (${total})`);
    opt.value = nombre;
    selectPrincipio.append(opt);
  }

  for (const { nombre, total } of marcas) {
    const opt = el("option", "", `${nombre} (${total})`);
    opt.value = nombre;
    selectMarca.append(opt);
  }

  selectPrincipio.disabled = false;
  selectMarca.disabled = false;
  selectOrden.disabled = false;
  checkEquivalentes.disabled = false;
}

function obtenerFiltrosActivos() {
  return {
    farmacia: farmaciaSeleccionada,
    principio: selectPrincipio.value,
    marca: selectMarca.value,
    orden: selectOrden.value,
    incluirEquivalentes: checkEquivalentes.checked,
  };
}

function hayAlgunFiltro() {
  return Boolean(
    normalizar(entrada.value).length >= MIN_CARACTERES ||
      farmaciaSeleccionada ||
      selectPrincipio.value ||
      selectMarca.value
  );
}

function pintar(limiteGrupos = GRUPOS_POR_PAGINA) {
  const consulta = entrada.value;
  const filtros = obtenerFiltrosActivos();

  btnLimpiar.hidden = !hayAlgunFiltro();
  cerrarPanel();
  resultados.replaceChildren();

  if (!hayAlgunFiltro()) {
    inicio.hidden = false;
    estado.textContent = "";
    return;
  }
  inicio.hidden = true;

  const grupos = buscar(productos, consulta, filtros);
  if (!grupos.length) {
    estado.textContent = "No encontramos productos con esa combinación de búsqueda y filtros.";
    return;
  }

  const total = grupos.reduce((n, g) => n + g.items.length, 0);
  const coinciden = grupos.reduce((n, g) => n + g.coincidencias, 0);

  let resumenFiltros = [];
  if (filtros.farmacia) resumenFiltros.push(`en ${filtros.farmacia}`);
  if (filtros.principio) resumenFiltros.push(`categoría ${filtros.principio}`);
  if (filtros.marca) resumenFiltros.push(`marca ${filtros.marca}`);
  const sufijoFiltros = resumenFiltros.length ? ` [${resumenFiltros.join(" · ")}]` : "";

  const enGrupos = `${plural(total, "producto", "productos")} en ${plural(grupos.length, "grupo", "grupos")}${sufijoFiltros}.`;
  estado.textContent =
    coinciden === total
      ? `Mostrando ${enGrupos}`
      : `${plural(coinciden, "coincidencia directa", "coincidencias directas")}. Con equivalentes: ${enGrupos}`;

  const gruposVisibles = grupos.slice(0, limiteGrupos);
  resultados.append(...gruposVisibles.map(grupo));

  if (grupos.length > limiteGrupos) {
    const restan = grupos.length - limiteGrupos;
    const contenedorMas = el("div", "contenedor-mas");
    const btnMas = el("button", "btn-cargar-mas", `Mostrar más grupos (${restan.toLocaleString("es-CO")} restantes)`);
    btnMas.type = "button";
    btnMas.addEventListener("click", () => pintar(limiteGrupos + GRUPOS_POR_PAGINA));
    contenedorMas.append(btnMas);
    resultados.append(contenedorMas);
  }
}

// Eventos de filtros y búsqueda
let temporizador;
entrada.addEventListener("input", () => {
  clearTimeout(temporizador);
  temporizador = setTimeout(() => pintar(), ESPERA_MS);
});

selectPrincipio.addEventListener("change", () => pintar());
selectMarca.addEventListener("change", () => pintar());
selectOrden.addEventListener("change", () => pintar());
checkEquivalentes.addEventListener("change", () => pintar());

btnLimpiar.addEventListener("click", () => {
  entrada.value = "";
  farmaciaSeleccionada = "";
  selectPrincipio.value = "";
  selectMarca.value = "";
  selectOrden.value = "unidad_asc";
  checkEquivalentes.checked = true;
  actualizarEstadoKPIs();
  pintar();
  entrada.focus();
});

btnVistaCuadricula.addEventListener("click", () => {
  modoVista = "cuadricula";
  btnVistaCuadricula.classList.add("activo");
  btnVistaLista.classList.remove("activo");
  for (const ol of resultados.querySelectorAll(".tarjetas")) ol.classList.remove("vista-lista");
});

btnVistaLista.addEventListener("click", () => {
  modoVista = "lista";
  btnVistaLista.classList.add("activo");
  btnVistaCuadricula.classList.remove("activo");
  for (const ol of resultados.querySelectorAll(".tarjetas")) ol.classList.add("vista-lista");
});

$("buscador").addEventListener("submit", (e) => {
  e.preventDefault();
  clearTimeout(temporizador);
  pintar();
});

inicio.addEventListener("click", (e) => {
  const boton = e.target.closest("[data-ejemplo]");
  if (!boton) return;
  entrada.value = boton.dataset.ejemplo;
  pintar();
  entrada.focus();
});

$("cerrar-panel").addEventListener("click", () => cerrarPanel(true));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") cerrarPanel(true);
});

const aviso = document.querySelector(".aviso");
new ResizeObserver(() => {
  document.documentElement.style.setProperty("--alto-aviso", `${aviso.offsetHeight}px`);
}).observe(aviso);

async function cargar() {
  const fecha = $("fecha-datos");
  try {
    const resp = await fetch(RUTA_DATOS, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    productos = preparar(parsearCSV(await resp.text()));
    mostrarKPIs(productos);
    poblarSelectores(productos);
  } catch (err) {
    console.error(err);
    fecha.textContent = "Sin datos";
    estado.classList.add("error");
    estado.textContent =
      location.protocol === "file:"
        ? "No se pudieron cargar los precios: abre la página desde un servidor (python -m http.server), no como archivo."
        : "No se pudieron cargar los precios. Intenta de nuevo más tarde.";
    return;
  }

  const rango = rangoFechas(productos);
  fecha.textContent = !rango
    ? "Fecha de los precios no disponible"
    : rango.desde === rango.hasta
      ? `Precios consultados el ${fechaLarga(rango.hasta)}`
      : `Precios consultados entre el ${fechaLarga(rango.desde)} y el ${fechaLarga(rango.hasta)}`;

  entrada.disabled = false;
  pintar();
}

function alternarProductoCarrito(p, art, btn) {
  const id = idProductoCarrito(p);
  if (carrito.has(id)) {
    carrito.delete(id);
    art.classList.remove("en-carrito");
    btn.classList.remove("activo");
    btn.textContent = "+ Agrupar";
  } else {
    carrito.set(id, p);
    art.classList.add("en-carrito");
    btn.classList.add("activo");
    btn.textContent = "✓ Agrupado";
  }
  actualizarBarraCarrito();
}

function actualizarBarraCarrito() {
  const items = [...carrito.values()];
  if (items.length === 0) {
    barraCarrito.hidden = true;
    return;
  }
  barraCarrito.hidden = false;
  const gruposUnicos = new Set(items.map(claveFilaConsciente));
  carritoContador.textContent = plural(items.length, "producto seleccionado", "productos seleccionados");
  carritoGrupos.textContent = `en ${plural(gruposUnicos.size, "fila comparativa", "filas comparativas")}`;
}

function escaparHTML(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function exportarMatrizExcel() {
  const seleccionados = [...carrito.values()];
  if (!seleccionados.length) return;

  const { farmacias, filas } = construirMatrizComparativa(seleccionados, "total");

  let htmlTabla = `
    <html xmlns:o="urn:schemas-microsoft-com:office:office"
          xmlns:x="urn:schemas-microsoft-com:office:excel"
          xmlns="http://www.w3.org/TR/REC-html40">
    <head>
      <meta charset="utf-8">
      <style>
        table { border-collapse: collapse; font-family: Segoe UI, Arial, sans-serif; font-size: 11pt; }
        th { background-color: #0077B6; color: #ffffff; font-weight: bold; border: 1px solid #2b2b2b; padding: 10px; text-align: center; }
        td { border: 1px solid #bfbfbf; padding: 8px 10px; vertical-align: middle; }
        .col-prod { font-weight: bold; background-color: #f6f5f1; text-align: left; }
        .precio { text-align: right; font-weight: bold; font-size: 12pt; }
        .detalle { font-size: 8.5pt; color: #555555; font-weight: normal; display: block; }
        .minimo { background-color: #c6efce; color: #006100; }
        .maximo { background-color: #ffc7ce; color: #9c0006; }
        .col-min { background-color: #eef7fc; font-weight: bold; text-align: right; }
      </style>
    </head>
    <body>
      <table>
        <thead>
          <tr>
            <th>MEDICAMENTO / SUSTANCIA</th>
            ${farmacias.map((f) => `<th>${escaparHTML(f.toUpperCase())}</th>`).join("")}
            <th>MIN</th>
          </tr>
        </thead>
        <tbody>
  `;

  for (const fila of filas) {
    htmlTabla += `<tr>`;
    htmlTabla += `<td class="col-prod">${escaparHTML(fila.titulo)}</td>`;

    for (const farm of farmacias) {
      const prod = fila.porFarmacia.get(farm);
      if (!prod || prod.precioNum === null) {
        htmlTabla += `<td style="text-align:center; color:#999999;">—</td>`;
        continue;
      }

      let claseColor = "";
      if (fila.min !== null && prod.precioNum === fila.min) {
        claseColor = "minimo";
      } else if (fila.max !== null && prod.precioNum === fila.max && fila.max > fila.min) {
        claseColor = "maximo";
      }

      const detalle = `${prod.producto} (${prod.presentacion || "UND"})`;
      htmlTabla += `
        <td class="precio ${claseColor}">
          ${pesos.format(prod.precioNum)}
          <br><span class="detalle">${escaparHTML(detalle)}</span>
        </td>
      `;
    }

    const textoMin = fila.min !== null ? pesos.format(fila.min) : "—";
    htmlTabla += `<td class="col-min">${textoMin}</td>`;
    htmlTabla += `</tr>`;
  }

  htmlTabla += `
        </tbody>
      </table>
    </body>
    </html>
  `;

  const blob = new Blob(["\ufeff", htmlTabla], { type: "application/vnd.ms-excel;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const hoy = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `comparativa-recetapp-${hoy}.xls`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

btnVaciarCarrito.addEventListener("click", () => {
  carrito.clear();
  actualizarBarraCarrito();
  pintar();
});

btnExportarCarrito.addEventListener("click", () => exportarMatrizExcel());

cargar();