# Sistema de Consulta PAI / ADRES

Herramienta de escritorio para consultas masivas en los portales del **PAI**
(menores y mayores) y del **Comprobador de Derechos / ADRES**, a partir de un
listado de documentos en CSV.

Integración: Diego A. Ortega — Subred Sur / SDS.
Base original: Luis Silva — SISVAN.

---

## ⚠️ Antes que nada: datos personales

Los CSV de entrada y los archivos de salida contienen documentos, nombres,
direcciones y teléfonos de personas. Son datos personales sensibles cubiertos
por la **Ley 1581 de 2012 (Habeas Data)**.

El archivo `.gitignore` de este repositorio bloquea `*.csv` y `*.xlsx` a
propósito. **No lo modifiques para forzar la subida de datos.** Si alguna vez
un archivo con datos llega a un commit, no basta con borrarlo: queda en el
historial de Git y hay que reescribirlo.

---

## Contenido

| Ruta | Qué es |
|---|---|
| `Busqueda.py` | La aplicación completa (tkinter + Selenium) |
| `requirements.txt` | Dependencias de Python |
| `web/` | Sitio publicado en Netlify (portada y descarga) |
| `netlify/edge-functions/auth.ts` | Control de acceso del sitio |
| `netlify.toml` | Configuración de Netlify |
| `.github/workflows/publicar.yml` | Compila el `.exe` y despliega el sitio |

---

## Uso local (con Python)

```bash
git clone https://github.com/USUARIO/REPO.git
cd REPO
python -m venv .venv
.venv\Scripts\activate        # en Windows
pip install -r requirements.txt
python Busqueda.py
```

Requisitos: Python 3.10 o superior y Google Chrome instalado.
**No hace falta descargar chromedriver**: Selenium Manager lo resuelve solo y
empareja la versión con el Chrome del equipo.

### Flujo de trabajo

1. Abre la aplicación y elige el módulo.
2. Pulsa **🌐 Iniciar Chrome (sesión)**. Se abre Chrome con un perfil propio
   guardado en `~/.pai_perfil_chrome` y con el puerto de depuración `9222`.
3. Inicia sesión en el portal dentro de esa ventana. Como el perfil es
   persistente, la sesión sobrevive entre ejecuciones.
4. Carga el CSV, que debe traer las columnas `consecutivo` y `codigo`.
5. Elige una consulta predeterminada o la **personalizada** (campo por campo).
6. **▶ Iniciar consulta**. La salida se guarda en la carpeta de trabajo y se
   actualiza registro a registro, así que un corte no pierde lo ya procesado.

---

## Compilar el ejecutable a mano

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name Busqueda Busqueda.py
```

El resultado queda en `dist/Busqueda.exe`. En la práctica no hace falta: el
workflow de GitHub Actions lo compila en cada push a `main`.

---

## Despliegue del sitio (Netlify)

El sitio sirve la descarga detrás de un login de usuarios validado **en el
servidor**, mediante una Edge Function. Las credenciales viven en variables de
entorno de Netlify y nunca se guardan en el repositorio.

### 1. Variables de entorno

En Netlify: *Project configuration → Environment variables*.

| Variable | Contenido |
|---|---|
| `USUARIOS_APP` | `usuario1:hash1,usuario2:hash2,usuario3:hash3` |
| `SECRETO_SESION` | Una cadena aleatoria larga (firma la cookie) |

Los hashes son SHA-256 de la contraseña, en hexadecimal:

```bash
python -c "import hashlib;print(hashlib.sha256('MiClaveSegura'.encode()).hexdigest())"
```

Y el secreto de sesión:

```bash
python -c "import secrets;print(secrets.token_hex(32))"
```

Ejemplo del valor final de `USUARIOS_APP`:

```
diego:5e88489...,luis:a3f91c2...,ana:7bd0e44...
```

### 2. Secretos de GitHub

En el repositorio: *Settings → Secrets and variables → Actions*.

| Secreto | Dónde sale |
|---|---|
| `NETLIFY_AUTH_TOKEN` | Netlify → *User settings → Applications → Personal access tokens* |
| `NETLIFY_SITE_ID` | Netlify → *Project configuration → General → Project ID* |

### 3. Desactivar el build automático de Netlify

Como el despliegue lo hace GitHub Actions (es el único que puede compilar un
`.exe` de Windows), hay que evitar que Netlify despliegue por su cuenta y pise
la versión con la descarga.

En Netlify: *Project configuration → Build & deploy → Continuous deployment →
Build settings → **Stop builds***.

A partir de ahí, cada push a `main` compila el ejecutable, lo mete en
`web/descargas/` y publica todo el sitio.

---

## Sobre la seguridad del acceso

- La validación ocurre en la Edge Function, **antes** de entregar cualquier
  archivo del sitio. El `.exe` no es accesible sin sesión iniciada.
- El ejecutable **no se sube al repositorio**: lo produce el workflow y viaja
  directo al sitio protegido. Por eso el repositorio puede ser público sin
  exponer la descarga.
- La cookie de sesión va firmada con HMAC-SHA256, marcada `HttpOnly`, `Secure`
  y `SameSite=Strict`, y vence a las 12 horas.
- Un intento fallido de ingreso tarda ~1,2 s a propósito, para encarecer los
  ataques por fuerza bruta.

Esto es un control razonable para una herramienta interna, no un sistema de
autenticación institucional. Usa contraseñas largas y distintas para cada
usuario, y cámbialas si alguien deja el equipo o el rol.
