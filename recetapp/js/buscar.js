// Búsqueda, filtrado multidimensional, agrupación y orden de productos. Sin DOM.

export const MIN_CARACTERES = 2;

export function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

export function numero(valor) {
  const texto = String(valor ?? "").trim();
  if (texto === "") return null;
  const n = Number(texto);
  return Number.isFinite(n) ? n : null;
}

// Prepara las filas del CSV una sola vez: números, descuentos y texto de búsqueda normalizado.
export function preparar(filas) {
  return filas.map((f) => {
    const precioNum = numero(f.precio);
    const precioListaNum = numero(f.precio_lista);
    const precioUnidadNum = numero(f.precio_unidad);
    const unidadesNum = numero(f.unidades) || 1;
    const descuentoPct =
      precioNum !== null && precioListaNum !== null && precioListaNum > precioNum
        ? ((precioListaNum - precioNum) / precioListaNum) * 100
        : 0;

    return {
      ...f,
      precioNum,
      precioListaNum,
      precioUnidadNum,
      unidadesNum,
      descuentoPct,
      busqueda: normalizar([f.producto, f.marca, f.principio_activo, f.concentracion, f.presentacion, f.codigo].join(" ")),
    };
  });
}

// Extrae las listas únicas de Categorías/Principios y Marcas ordenadas por frecuencia/alfabéticamente.
export function extraerOpcionesFiltros(productos) {
  const conteoPrincipios = new Map();
  const conteoMarcas = new Map();

  for (const p of productos) {
    const pa = (p.principio_activo || "").trim();
    if (pa && pa !== "N/A") {
      conteoPrincipios.set(pa, (conteoPrincipios.get(pa) || 0) + 1);
    }
    const marca = (p.marca || "").trim();
    if (marca && marca !== "N/A") {
      conteoMarcas.set(marca, (conteoMarcas.get(marca) || 0) + 1);
    }
  }

  // Ponemos primero las 9 Macrocategorías y luego los principios activos alfabéticamente
  const principios = [...conteoPrincipios.entries()]
    .sort((a, b) => {
      const aMacro = CATEGORIAS_MACRO.has(a[0].toUpperCase());
      const bMacro = CATEGORIAS_MACRO.has(b[0].toUpperCase());
      if (aMacro && !bMacro) return -1;
      if (!aMacro && bMacro) return 1;
      return a[0].localeCompare(b[0], "es");
    })
    .map(([nombre, total]) => ({
      nombre,
      total,
      esMacro: CATEGORIAS_MACRO.has(nombre.toUpperCase()),
    }));

  const marcas = [...conteoMarcas.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], "es"))
    .map(([nombre, total]) => ({ nombre, total }));

  return { principios, marcas };
} 

// Verifica si un producto cumple con los filtros directos (texto, farmacia, principio, marca).
export function filtrar(productos, consulta, filtros = {}) {
  const q = normalizar(consulta);
  const { farmacia = "", principio = "", marca = "" } = filtros;

  const hayFiltroActivo = Boolean(farmacia || principio || marca);
  if (q.length < MIN_CARACTERES && !hayFiltroActivo) return [];

  const palabras = q.length >= MIN_CARACTERES ? q.split(" ") : [];

  return productos.filter((p) => {
    if (farmacia && p.farmacia !== farmacia) return false;
    if (principio && p.principio_activo !== principio) return false;
    if (marca && p.marca !== marca) return false;
    if (palabras.length > 0 && !palabras.every((w) => p.busqueda.includes(w))) return false;
    return true;
  });
}

const ORDEN_UNIDAD = { mcg: 0, ui: 1, mg: 2, g: 3, "%": 4 };

function claveConcentracion(concentracion) {
  const m = /^([\d.]+)\s*(\S+)/.exec(normalizar(concentracion));
  if (!m) return [9, 0];
  return [ORDEN_UNIDAD[m[2]] ?? 8, Number(m[1])];
}

function compararPorUnidad(a, b) {
  if (a.precioUnidadNum === null && b.precioUnidadNum === null) return 0;
  if (a.precioUnidadNum === null) return 1;
  if (b.precioUnidadNum === null) return -1;
  return a.precioUnidadNum - b.precioUnidadNum;
}

function compararProductos(a, b, orden) {
  switch (orden) {
    case "precio_asc":
      return (a.precioNum ?? Infinity) - (b.precioNum ?? Infinity);
    case "precio_desc":
      return (b.precioNum ?? -Infinity) - (a.precioNum ?? -Infinity);
    case "descuento_desc":
      return (b.descuentoPct || 0) - (a.descuentoPct || 0) || compararPorUnidad(a, b);
    case "unidad_asc":
    default:
      return compararPorUnidad(a, b);
  }
}

const claveGrupo = (p) => `${p.principio_activo}|${p.concentracion}|${p.unidadesNum || 1}`;

// Categorías genéricas amplias donde NO conviene mezclar todos los productos como "equivalentes"
export const CATEGORIAS_MACRO = new Set([
  "MEDICAMENTOS Y FARMACIA",
  "CUIDADO PERSONAL Y ASEO",
  "DERMOCOSMÉTICA Y BELLEZA",
  "DERMOCOSMETICA Y BELLEZA",
  "NUTRICIÓN Y SUPLEMENTOS",
  "NUTRICION Y SUPLEMENTOS",
  "BEBÉ Y MATERNIDAD",
  "BEBE Y MATERNIDAD",
  "DISPOSITIVOS Y BOTIQUÍN",
  "DISPOSITIVOS Y BOTIQUIN",
  "ALIMENTOS Y BEBIDAS",
  "SALUD SEXUAL",
  "ACCESORIOS Y HOGAR",
]);

export function buscar(productos, consulta, filtros = {}) {
  const {
    farmacia = "",
    principio = "",
    marca = "",
    orden = "unidad_asc",
    incluirEquivalentes = true,
  } = filtros;

  const directos = filtrar(productos, consulta, { farmacia, principio, marca });
  if (!directos.length) return [];

  const coincidencias = new Set(directos);
  const clavesBuscadas = new Set(directos.map(claveGrupo));

  const grupos = new Map();
  for (const p of productos) {
    const clave = claveGrupo(p);
    if (!clavesBuscadas.has(clave)) continue;

    // Si hay filtro de farmacia activo, respetarlo siempre en la vista
    if (farmacia && p.farmacia !== farmacia) continue;

    const esCoincidenciaDirecta = coincidencias.has(p);
    const esMacroCategoria = CATEGORIAS_MACRO.has(normalizar(p.principio_activo).toUpperCase());

    // Solo incluimos equivalentes de otras marcas si el usuario lo activó y es un principio farmacológico real
    if (!esCoincidenciaDirecta && (!incluirEquivalentes || esMacroCategoria)) {
      continue;
    }

    if (!grupos.has(clave)) {
      grupos.set(clave, {
        principio: p.principio_activo,
        concentracion: p.concentracion,
        unidades: p.unidadesNum || 1,
        items: [],
      });
    }
    grupos.get(clave).items.push({ producto: p, coincide: esCoincidenciaDirecta, masBarata: false });
  }

  const lista = [...grupos.values()];
  for (const g of lista) {
    g.items.sort((a, b) => compararProductos(a.producto, b.producto, orden));
    const precios = g.items.map((it) => it.producto.precioUnidadNum).filter((n) => n !== null);
    g.minimo = precios.length ? Math.min(...precios) : null;
    for (const it of g.items) {
      it.masBarata = g.minimo !== null && it.producto.precioUnidadNum === g.minimo && g.items.length > 1;
    }
    g.coincidencias = g.items.filter((it) => it.coincide).length;
  }

  return lista.sort((a, b) => {
    const porPrincipio = a.principio.localeCompare(b.principio, "es");
    if (porPrincipio) return porPrincipio;
    const [ua, va] = claveConcentracion(a.concentracion);
    const [ub, vb] = claveConcentracion(b.concentracion);
    if (ua !== ub || va !== vb) return ua - ub || va - vb;
    return a.unidades - b.unidades;
  });
}

export function masBaratoQue(productos, elegido) {
  const unidades = numero(elegido.unidades);
  if (elegido.precioUnidadNum === null || !unidades) return { tipo: "sin-unidades" };

  const clave = claveGrupo(elegido);
  const comparables = productos.filter((p) => claveGrupo(p) === clave && p.precioUnidadNum !== null);
  const mejor = comparables.reduce((a, b) => (b.precioUnidadNum < a.precioUnidadNum ? b : a), elegido);

  if (mejor.precioUnidadNum >= elegido.precioUnidadNum) {
    return { tipo: "es-la-mas-barata", unico: comparables.length <= 1 };
  }

  const ahorroUnidad = elegido.precioUnidadNum - mejor.precioUnidadNum;
  const costoElegido = elegido.precioUnidadNum * unidades;
  const costoMejor = mejor.precioUnidadNum * unidades;
  return {
    tipo: "hay-mas-barata",
    mejor,
    unidades,
    ahorroUnidad,
    porcentaje: (ahorroUnidad / elegido.precioUnidadNum) * 100,
    costoElegido,
    costoMejor,
    ahorroTotal: costoElegido - costoMejor,
  };
}

export function rangoFechas(productos) {
  const fechas = productos.map((p) => p.fecha).filter((f) => /^\d{4}-\d{2}-\d{2}$/.test(f)).sort();
  if (!fechas.length) return null;
  return { desde: fechas[0], hasta: fechas[fechas.length - 1] };
}

// Identificador único de producto para el carrito
export function idProductoCarrito(p) {
  return `${p.farmacia}|${p.codigo}|${p.producto}`;
}

// Clave consciente para filas de la matriz: Sustancia + Concentración + Cantidad de Unidades
export function claveFilaConsciente(p) {
  const pa = (p.principio_activo || "SIN CLASIFICAR").trim().toUpperCase();
  const conc = (p.concentracion && p.concentracion !== "N/A") ? p.concentracion.trim().toUpperCase() : "";
  const unds = p.unidadesNum || numero(p.unidades) || 1;
  return `${pa}|${conc}|X${unds}`;
}

export function construirMatrizComparativa(productosSeleccionados, modoPrecio = "total") {
  const ordenFarmacias = [
    "Tu Droguería Virtual",
    "Habib Droguerías",
    "Cruz Verde",
    "La Rebaja",
    "Farmatodo",
    "La Economía",
  ];

  const setFarmacias = new Set(productosSeleccionados.map((p) => p.farmacia));
  const farmacias = [
    ...ordenFarmacias.filter((f) => setFarmacias.has(f)),
    ...[...setFarmacias].filter((f) => !ordenFarmacias.includes(f)).sort(),
  ];

  const mapaFilas = new Map();

  for (const p of productosSeleccionados) {
    const clave = claveFilaConsciente(p);
    if (!mapaFilas.has(clave)) {
      const unds = p.unidadesNum || numero(p.unidades) || 1;
      const partesTitulo = [p.principio_activo];
      if (p.concentracion && p.concentracion !== "N/A") partesTitulo.push(p.concentracion);
      partesTitulo.push(`X ${unds} UND`);

      mapaFilas.set(clave, {
        clave,
        principio: p.principio_activo,
        concentracion: p.concentracion || "N/A",
        unidades: unds,
        titulo: partesTitulo.join(" · "),
        porFarmacia: new Map(),
      });
    }

    const fila = mapaFilas.get(clave);
    const actual = fila.porFarmacia.get(p.farmacia);

    const valorNuevo = modoPrecio === "unidad" ? (p.precioUnidadNum ?? p.precioNum) : p.precioNum;
    const valorActual = actual
      ? (modoPrecio === "unidad" ? (actual.precioUnidadNum ?? actual.precioNum) : actual.precioNum)
      : Infinity;

    if (!actual || (valorNuevo !== null && valorNuevo < valorActual)) {
      fila.porFarmacia.set(p.farmacia, p);
    }
  }

  const filas = [...mapaFilas.values()].map((f) => {
    const valores = [];
    for (const farm of farmacias) {
      const prod = f.porFarmacia.get(farm);
      if (prod) {
        const val = modoPrecio === "unidad" ? (prod.precioUnidadNum ?? prod.precioNum) : prod.precioNum;
        if (val !== null) valores.push(val);
      }
    }
    const min = valores.length ? Math.min(...valores) : null;
    const max = valores.length ? Math.max(...valores) : null;
    return { ...f, min, max };
  });

  filas.sort((a, b) => a.titulo.localeCompare(b.titulo, "es"));
  return { farmacias, filas };
}