// Lector de CSV (RFC 4180): comas, comillas escapadas ("") y saltos de línea
// dentro de campos entre comillas, CRLF, BOM y línea final vacía.

export function parsearCSV(texto) {
  const filas = [];
  let fila = [];
  let campo = "";
  let entreComillas = false;
  let i = texto.charCodeAt(0) === 0xfeff ? 1 : 0; // BOM

  for (; i < texto.length; i++) {
    const c = texto[i];
    if (entreComillas) {
      if (c === '"') {
        if (texto[i + 1] === '"') {
          campo += '"';
          i++;
        } else {
          entreComillas = false;
        }
      } else {
        campo += c;
      }
    } else if (c === '"') {
      entreComillas = true;
    } else if (c === ",") {
      fila.push(campo);
      campo = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && texto[i + 1] === "\n") i++;
      fila.push(campo);
      filas.push(fila);
      fila = [];
      campo = "";
    } else {
      campo += c;
    }
  }
  if (campo !== "" || fila.length > 0) {
    fila.push(campo);
    filas.push(fila);
  }

  const [encabezado, ...datos] = filas.filter((f) => !(f.length === 1 && f[0] === ""));
  if (!encabezado) return [];
  return datos.map((f) => Object.fromEntries(encabezado.map((col, j) => [col.trim(), f[j] ?? ""])));
}
