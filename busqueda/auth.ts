// ─────────────────────────────────────────────────────────────
//  Control de acceso al sitio — Netlify Edge Function
//
//  Valida usuario y contraseña EN EL SERVIDOR antes de entregar
//  cualquier archivo del sitio (incluido el .exe). Las credenciales
//  viven en variables de entorno de Netlify, nunca en el repositorio.
//
//  Variables de entorno requeridas (Netlify > Project configuration >
//  Environment variables):
//
//    USUARIOS_APP    usuario:hash,usuario:hash,usuario:hash
//                    donde hash = SHA-256 en hexadecimal de la contraseña
//    SECRETO_SESION  cadena aleatoria larga (firma la cookie de sesión)
//
//  Para generar un hash:
//    python -c "import hashlib;print(hashlib.sha256('MiClave'.encode()).hexdigest())"
// ─────────────────────────────────────────────────────────────

const HORAS_SESION = 12;

// ---------- utilidades ----------

function bytesAHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256Hex(texto: string): Promise<string> {
  const datos = new TextEncoder().encode(texto);
  return bytesAHex(await crypto.subtle.digest("SHA-256", datos));
}

async function firmar(mensaje: string, secreto: string): Promise<string> {
  const clave = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secreto),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const firma = await crypto.subtle.sign(
    "HMAC",
    clave,
    new TextEncoder().encode(mensaje),
  );
  return bytesAHex(firma);
}

/** Comparación en tiempo constante: no filtra información por demora. */
function iguales(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let dif = 0;
  for (let i = 0; i < a.length; i++) dif |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return dif === 0;
}

function leerCookie(request: Request, nombre: string): string | null {
  const cabecera = request.headers.get("cookie") || "";
  for (const parte of cabecera.split(";")) {
    const [clave, ...resto] = parte.trim().split("=");
    if (clave === nombre) return resto.join("=");
  }
  return null;
}

function usuariosConfigurados(): Map<string, string> {
  const crudo = Deno.env.get("USUARIOS_APP") || "";
  const mapa = new Map<string, string>();
  for (const entrada of crudo.split(",")) {
    const [usuario, hash] = entrada.split(":");
    if (usuario && hash) mapa.set(usuario.trim(), hash.trim().toLowerCase());
  }
  return mapa;
}

// ---------- sesión ----------

async function crearToken(usuario: string, secreto: string): Promise<string> {
  const expira = Date.now() + HORAS_SESION * 3600 * 1000;
  const cuerpo = `${usuario}.${expira}`;
  return `${cuerpo}.${await firmar(cuerpo, secreto)}`;
}

async function tokenValido(token: string | null, secreto: string): Promise<boolean> {
  if (!token) return false;
  const partes = token.split(".");
  if (partes.length !== 3) return false;
  const [usuario, expira, firma] = partes;
  if (!/^\d+$/.test(expira) || Number(expira) < Date.now()) return false;
  return iguales(firma, await firmar(`${usuario}.${expira}`, secreto));
}

// ---------- pantalla de ingreso ----------

function paginaLogin(error = ""): string {
  return `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Acceso — Sistema de Consulta PAI / ADRES</title>
<style>
  :root { --azul:#1a73e8; --azul-osc:#1558b0; --gris:#f0f4f8; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:grid; place-items:center;
         background:var(--gris); font-family:"Segoe UI",system-ui,sans-serif; color:#212121; }
  .caja { background:#fff; width:min(400px,92vw); border-radius:12px;
          box-shadow:0 10px 40px rgba(0,0,0,.12); overflow:hidden; }
  .cab { background:var(--azul); color:#fff; padding:26px 24px; text-align:center; }
  .cab h1 { margin:0; font-size:19px; }
  .cab p { margin:6px 0 0; font-size:12px; color:#c8d8f8; }
  form { padding:24px; }
  label { display:block; font-size:13px; font-weight:600; margin:14px 0 5px; }
  input { width:100%; padding:11px 12px; border:1px solid #ccd; border-radius:7px;
          font-size:14px; font-family:inherit; }
  input:focus { outline:2px solid var(--azul); border-color:transparent; }
  button { width:100%; margin-top:22px; padding:12px; border:0; border-radius:7px;
           background:var(--azul); color:#fff; font-size:15px; font-weight:700;
           cursor:pointer; font-family:inherit; }
  button:hover { background:var(--azul-osc); }
  .error { margin-top:16px; padding:10px 12px; border-radius:7px;
           background:#fdecea; color:#b3261e; font-size:13px; }
  .pie { padding:0 24px 20px; font-size:11px; color:#888; text-align:center; }
</style>
</head>
<body>
  <div class="caja">
    <div class="cab">
      <h1>🏥 Sistema de Consulta PAI / ADRES</h1>
      <p>Acceso restringido — Subred Sur</p>
    </div>
    <form method="POST" action="/entrar">
      <label for="usuario">Usuario</label>
      <input id="usuario" name="usuario" autocomplete="username" required autofocus>
      <label for="clave">Contraseña</label>
      <input id="clave" name="clave" type="password" autocomplete="current-password" required>
      <button type="submit">Ingresar</button>
      ${error ? `<div class="error">${error}</div>` : ""}
    </form>
    <div class="pie">Uso institucional. La herramienta accede a datos personales
    protegidos por la Ley 1581 de 2012.</div>
  </div>
</body>
</html>`;
}

function respuestaLogin(error = "", estado = 401): Response {
  return new Response(paginaLogin(error), {
    status: estado,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-robots-tag": "noindex, nofollow",
    },
  });
}

// ---------- handler ----------

export default async function (request: Request, context: any) {
  const secreto = Deno.env.get("SECRETO_SESION");
  const usuarios = usuariosConfigurados();

  if (!secreto || usuarios.size === 0) {
    return new Response(
      "Sitio sin configurar: faltan las variables USUARIOS_APP y/o SECRETO_SESION.",
      { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } },
    );
  }

  const url = new URL(request.url);

  // Cerrar sesión
  if (url.pathname === "/salir") {
    return new Response(null, {
      status: 302,
      headers: {
        location: "/",
        "set-cookie": "sesion=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict",
      },
    });
  }

  // Intento de ingreso
  if (request.method === "POST" && url.pathname === "/entrar") {
    const datos = await request.formData();
    const usuario = String(datos.get("usuario") || "").trim();
    const clave = String(datos.get("clave") || "");

    const hashEsperado = usuarios.get(usuario);
    const hashRecibido = await sha256Hex(clave);

    if (!hashEsperado || !iguales(hashEsperado, hashRecibido)) {
      // Retardo para encarecer la fuerza bruta
      await new Promise((r) => setTimeout(r, 1200));
      return respuestaLogin("Usuario o contraseña incorrectos.");
    }

    const token = await crearToken(usuario, secreto);
    return new Response(null, {
      status: 302,
      headers: {
        location: "/",
        "set-cookie":
          `sesion=${token}; Path=/; Max-Age=${HORAS_SESION * 3600}; ` +
          "HttpOnly; Secure; SameSite=Strict",
      },
    });
  }

  // Sesión válida → se sirve el sitio
  if (await tokenValido(leerCookie(request, "sesion"), secreto)) {
    return context.next();
  }

  return respuestaLogin();
}

export const config = { path: "/*" };
