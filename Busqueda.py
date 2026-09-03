# THIS CODE WAS CREATED BY LUIS DE SISVAN 2026
# Fusión: PAI Menores + PAI Mayores + ADRES/Comprobador de Derechos
# Integración realizada por Diego A. Ortega — Subred Sur / SDS 2026
#
# v3 — Cambios:
#   • Cronómetro: hora de inicio, hora final y duración (en vivo) en los 3 módulos.
#   • Búsqueda personalizada: además de las opciones predeterminadas, se pueden
#     elegir campos sueltos (p. ej. sólo teléfono + dirección) en PAI Menores,
#     PAI Mayores y en el Comprobador de Derechos.
#   • Sin chromedriver.exe: Selenium Manager descarga y empareja el driver solo.
#   • Botón "Iniciar Chrome (sesión)": lanza Chrome en modo depuración con un
#     perfil dedicado y persistente. Inicias sesión una vez en el PAI/ADRES y
#     ese navegador queda listo para todas las consultas siguientes.

import pandas as pd  # type: ignore
from selenium import webdriver  # type: ignore
from selenium.webdriver.common.by import By  # type: ignore
from selenium.webdriver.common.keys import Keys  # type: ignore
from selenium.common.exceptions import (  # type: ignore
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)
from selenium.webdriver.support.ui import Select, WebDriverWait  # type: ignore
from selenium.webdriver.support import expected_conditions as EC  # type: ignore
import os
import time
import socket
import shutil
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ─────────────────────────────────────────────
#  CHROME EN MODO DEPURACIÓN (perfil dedicado)
# ─────────────────────────────────────────────
PUERTO_DEBUG  = 9222
PERFIL_CHROME = str(Path.home() / ".pai_perfil_chrome")

RUTAS_CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
]


def buscar_chrome():
    """Devuelve la ruta del ejecutable de Chrome, o None si no se encuentra."""
    for ruta in RUTAS_CHROME:
        if ruta and os.path.isfile(ruta):
            return ruta
    for nombre in ("chrome", "google-chrome", "chromium"):
        hallado = shutil.which(nombre)
        if hallado:
            return hallado
    return None


def chrome_debug_activo(puerto=PUERTO_DEBUG):
    """True si ya hay un Chrome escuchando en el puerto de depuración."""
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=1):
            return True
    except OSError:
        return False


def lanzar_chrome_debug():
    """Abre Chrome con el puerto de depuración y un perfil propio y persistente.
    Devuelve (ok, mensaje)."""
    if chrome_debug_activo():
        return True, "Chrome ya está abierto en modo depuración. Puedes consultar."

    ruta = buscar_chrome()
    if not ruta:
        return False, ("No se encontró Chrome instalado. Instálalo o edita la "
                       "lista RUTAS_CHROME dentro del script.")

    os.makedirs(PERFIL_CHROME, exist_ok=True)
    try:
        subprocess.Popen([
            ruta,
            f"--remote-debugging-port={PUERTO_DEBUG}",
            f"--user-data-dir={PERFIL_CHROME}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://appb.saludcapital.gov.co/pai/",
        ])
    except Exception as e:
        return False, f"No se pudo abrir Chrome: {e}"

    for _ in range(20):          # hasta 10 s esperando que abra el puerto
        if chrome_debug_activo():
            return True, ("Chrome abierto. Inicia sesión en el PAI/ADRES en esa "
                          "ventana y luego vuelve aquí.")
        time.sleep(0.5)
    return False, "Chrome se abrió pero no respondió en el puerto de depuración."

# ─────────────────────────────────────────────
#  PALETA DE COLORES
# ─────────────────────────────────────────────
AZUL        = "#1a73e8"
AZUL_OSC    = "#1558b0"
VERDE       = "#2e7d32"
VERDE_OSC   = "#1b5e20"
NARANJA     = "#e65100"
NARANJA_OSC = "#bf360c"
MORADO      = "#6a1b9a"
MORADO_OSC  = "#4a148c"
GRIS        = "#f0f4f8"
BLANCO      = "#ffffff"
TEXTO       = "#212121"
FUENTE      = ("Segoe UI", 10)
FUENTE_T    = ("Segoe UI", 11, "bold")

# ─────────────────────────────────────────────
#  ESPERAS DINÁMICAS (sin time.sleep fijos)
# ─────────────────────────────────────────────
TIMEOUT = 30          # segundos máximos de espera por cada paso
TIMEOUT_CORTO = 15    # espera para saber si un código existe o no


def esperar_pagina_lista(driver, timeout=TIMEOUT):
    """Espera a que el navegador termine de cargar la página y a que
    ASP.NET AJAX (si lo usa) termine cualquier postback asíncrono."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.execute_script("""
            try {
                if (window.Sys && Sys.WebForms && Sys.WebForms.PageRequestManager) {
                    return !Sys.WebForms.PageRequestManager
                                .getInstance().get_isInAsyncPostBack();
                }
                return true;
            } catch (e) { return true; }
        """))
    except TimeoutException:
        pass


def click_y_esperar_postback(driver, elemento, timeout=TIMEOUT):
    """Hace clic y espera a que la página se recargue de verdad:
    el elemento clicado queda 'stale' cuando el postback reconstruye el DOM."""
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
    try:
        elemento.click()
    except (ElementClickInterceptedException, StaleElementReferenceException):
        driver.execute_script("arguments[0].click();", elemento)

    try:
        WebDriverWait(driver, timeout).until(EC.staleness_of(elemento))
    except TimeoutException:
        # postback parcial (UpdatePanel): el elemento puede seguir vivo
        pass
    esperar_pagina_lista(driver, timeout)


def esperar_valor(driver, id_campo, timeout=TIMEOUT):
    """Espera hasta que un input exista Y tenga valor real (no vacío).
    Devuelve el texto del value. Es la señal de que el detalle ya cargó."""
    def _con_valor(d):
        try:
            v = d.find_element(By.ID, id_campo).get_attribute("value")
            return v if (v is not None and v.strip() != "") else False
        except (NoSuchElementException, StaleElementReferenceException):
            return False
    return WebDriverWait(driver, timeout).until(_con_valor)


def leer_valor(driver, id_campo, timeout=TIMEOUT_CORTO):
    """Lee un input que puede venir legítimamente vacío (teléfono 2, etc.):
    espera a que exista y devuelve lo que tenga."""
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, id_campo))
        )
        return el.get_attribute("value") or ""
    except TimeoutException:
        raise NoSuchElementException(f"No apareció el campo {id_campo}")


def leer_select(driver, id_select, timeout=TIMEOUT_CORTO):
    """Espera a que el <select> exista y esté poblado (los combos en cascada
    —localidad, barrio, UPZ— se llenan por postbacks posteriores)."""
    def _poblado(d):
        try:
            el = d.find_element(By.ID, id_select)
            s = Select(el)
            if len(s.options) == 0:
                return False
            return s
        except (NoSuchElementException, StaleElementReferenceException):
            return False
    try:
        s = WebDriverWait(driver, timeout).until(_poblado)
        return s.first_selected_option.text
    except TimeoutException:
        raise NoSuchElementException(f"No se pobló el combo {id_select}")


# ─────────────────────────────────────────────
#  CRONÓMETRO  (hora de inicio / hora final / duración)
# ─────────────────────────────────────────────
def formato_duracion(delta):
    total = int(delta.total_seconds())
    h, resto = divmod(total, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class Cronometro:
    """Pinta 'Inicio | Fin | Duración' en un Label y lo refresca cada segundo
    mientras el proceso está corriendo. Seguro de llamar desde el hilo worker."""

    def __init__(self, root, label):
        self.root   = root
        self.label  = label
        self.inicio = None
        self.fin    = None
        self.activo = False
        self._pintar()

    # ---- API pública ----
    def iniciar(self):
        self.inicio = datetime.now()
        self.fin    = None
        self.activo = True
        self.root.after(0, self._pintar)
        self.root.after(1000, self._tick)
        return self.inicio

    def detener(self):
        self.fin    = datetime.now()
        self.activo = False
        self.root.after(0, self._pintar)
        return self.inicio, self.fin, (self.fin - self.inicio)

    @property
    def texto_resumen(self):
        if not self.inicio:
            return "Sin datos de tiempo."
        fin = self.fin or datetime.now()
        return (f"Hora de inicio: {self.inicio:%d/%m/%Y %H:%M:%S}\n"
                f"Hora final:     {fin:%d/%m/%Y %H:%M:%S}\n"
                f"Duración:       {formato_duracion(fin - self.inicio)}")

    # ---- interno ----
    def _tick(self):
        if self.activo:
            self._pintar()
            self.root.after(1000, self._tick)

    def _pintar(self):
        try:
            if not self.inicio:
                self.label.config(
                    text="🕒  Inicio: --:--:--     |     Fin: --:--:--     |     Duración: --"
                )
                return
            ini = self.inicio.strftime("%H:%M:%S")
            if self.fin:
                fin = self.fin.strftime("%H:%M:%S")
                dur = self.fin - self.inicio
            else:
                fin = "en curso…"
                dur = datetime.now() - self.inicio
            self.label.config(
                text=f"🕒  Inicio: {ini}     |     Fin: {fin}     |     "
                     f"Duración: {formato_duracion(dur)}"
            )
        except tk.TclError:
            # la ventana se cerró mientras corría el proceso
            self.activo = False


# ─────────────────────────────────────────────
#  CATÁLOGO DE CAMPOS PAI
#  clave: (etiqueta visible, tipo, id del control, modo)
#  tipo → "valor" = input   |   "select" = combo
#  modo → "ambos" | "menores"
# ─────────────────────────────────────────────
CAMPOS_PAI = {
    # Datos básicos
    "td":                  ("Tipo de documento (TD)",   "select", "ContentPlaceHolder1_ddl_TipoID",             "ambos"),
    "nombre2":             ("Segundo nombre",           "valor",  "ContentPlaceHolder1_txb_Nombre2",            "ambos"),
    "apellido2":           ("Segundo apellido",         "valor",  "ContentPlaceHolder1_txb_Apellido2",          "ambos"),
    "fecha_de_nacimiento": ("Fecha de nacimiento",      "valor",  "ContentPlaceHolder1_txb_FechaNacimiento",    "ambos"),
    "sexo":                ("Sexo",                     "select", "ContentPlaceHolder1_ddl_Genero",             "ambos"),
    "genero":              ("Género (LGBTI)",           "select", "ContentPlaceHolder1_ddl_GeneroLGBTI",        "ambos"),
    # Teléfono
    "telefono1":           ("Teléfono 1",               "valor",  "ContentPlaceHolder1_txb_Telefono1",          "ambos"),
    "telefono2":           ("Teléfono 2",               "valor",  "ContentPlaceHolder1_txb_Telefono2",          "ambos"),
    # Dirección
    "direccion":           ("Dirección",                "valor",  "ContentPlaceHolder1_txb_Direccion",          "ambos"),
    "direccionadicional":  ("Dato adicional dirección", "valor",  "ContentPlaceHolder1_txbDatoAdicionalDireccion", "ambos"),
    "departamento":        ("Departamento",             "select", "ContentPlaceHolder1_ddlDepartamento",        "ambos"),
    "municipio":           ("Municipio",                "select", "ContentPlaceHolder1_ddlMunicipios",          "ambos"),
    "localidad":           ("Localidad",                "select", "ContentPlaceHolder1_ddl_Localidad",          "ambos"),
    "upz":                 ("UPZ",                      "select", "ContentPlaceHolder1_ddlUPZ",                 "ambos"),
    "barrio":              ("Barrio",                   "select", "ContentPlaceHolder1_ddl_Barrio",             "ambos"),
    # EAPB
    "eapb":                ("EAPB / Aseguradora",       "select", "ContentPlaceHolder1_ddl_Aseguradora",        "ambos"),
    "regimen":             ("Régimen",                  "select", "ContentPlaceHolder1_ddl_Regimen",            "ambos"),
    # Datos de madre (sólo menores)
    "tdmadre":             ("TD de la madre",           "select", "ContentPlaceHolder1_ddl_TipoIDMadre",        "menores"),
    "docmadre":            ("Documento de la madre",    "valor",  "ContentPlaceHolder1_txb_IdentificacionMadre", "menores"),
    "nombrem1":            ("Primer nombre madre",      "valor",  "ContentPlaceHolder1_txb_Nombre1Madre",       "menores"),
    "nombrem2":            ("Segundo nombre madre",     "valor",  "ContentPlaceHolder1_txb_Nombre2Madre",       "menores"),
    "apellidomadre1":      ("Primer apellido madre",    "valor",  "ContentPlaceHolder1_txb_Apellido1Madre",     "menores"),
    "apellidomadre2":      ("Segundo apellido madre",   "valor",  "ContentPlaceHolder1_txb_Apellido2Madre",     "menores"),
}

# Agrupación usada por el selector personalizado
GRUPOS_CAMPOS = [
    ("Datos básicos",  ["td", "nombre2", "apellido2", "fecha_de_nacimiento", "sexo", "genero"]),
    ("Teléfono",       ["telefono1", "telefono2"]),
    ("Dirección",      ["direccion", "direccionadicional", "departamento",
                        "municipio", "localidad", "upz", "barrio"]),
    ("EAPB",           ["eapb", "regimen"]),
    ("Datos de madre", ["tdmadre", "docmadre", "nombrem1", "nombrem2",
                        "apellidomadre1", "apellidomadre2"]),
]

# Opciones predeterminadas = presets de campos
PRESETS_CAMPOS = {
    "1": ["td", "nombre2", "apellido2", "fecha_de_nacimiento", "sexo", "genero"],
    "2": ["telefono1", "telefono2"],
    "3": ["direccion", "municipio", "departamento", "localidad", "barrio",
          "upz", "direccionadicional"],
    "4": ["eapb", "regimen"],
    "5": ["tdmadre", "docmadre", "nombrem1", "nombrem2",
          "apellidomadre1", "apellidomadre2"],
}

OPCIONES_MENORES = [
    ("1", "Datos básicos",  "TD, ID, nombres, apellidos, fecha de nacimiento, sexo, género"),
    ("2", "Teléfono",       "ID, nombre, apellido, teléfono 1 y teléfono 2"),
    ("3", "Dirección",      "ID, nombre, apellido, dirección, municipio, dpto, localidad, barrio, UPZ"),
    ("4", "EAPB",           "ID, nombre, apellido, EAPB y régimen"),
    ("5", "Datos de madre", "ID, nombre, apellido, TD madre, doc madre, nombres y apellidos madre"),
]

OPCIONES_MAYORES = [
    ("1", "Datos básicos", "TD, ID, nombres, apellidos, fecha de nacimiento, sexo, género"),
    ("2", "Teléfono",      "ID, nombre, apellido, teléfono 1 y teléfono 2"),
    ("3", "Dirección",     "ID, nombre, apellido, dirección, municipio, dpto, localidad, barrio, UPZ"),
    ("4", "EAPB",          "ID, nombre, apellido, EAPB y régimen"),
]

NOMBRES_OPCIONES_TEXTO = {
    "1": "Datos_Basicos",
    "2": "Telefono",
    "3": "Direccion",
    "4": "EAPB",
    "5": "Datos_Madre",
    "P": "Personalizado",
}


def campos_disponibles(modo):
    """Claves de campo válidas para el módulo (menores incluye datos de madre)."""
    return [c for c, (_, _, _, m) in CAMPOS_PAI.items()
            if m == "ambos" or m == modo]


def extraer_campos(driver, claves):
    """Lee del formulario de detalle sólo los campos pedidos."""
    datos = {}
    for clave in claves:
        _, tipo, id_control, _ = CAMPOS_PAI[clave]
        if tipo == "select":
            datos[clave] = leer_select(driver, id_control)
        else:
            datos[clave] = leer_valor(driver, id_control)
    return datos


# ─────────────────────────────────────────────
#  SELECTOR DE CAMPOS PERSONALIZADO (PAI)
# ─────────────────────────────────────────────
def abrir_selector_campos(parent, modo, vars_campos, color, lbl_resumen, on_close):
    """Ventana modal con checkboxes agrupados para armar la consulta a la medida."""
    win = tk.Toplevel(parent)
    win.title("Personalizar campos de la consulta")
    win.configure(bg=GRIS)
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    hdr = tk.Frame(win, bg=color, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="⚙  Selecciona los campos que quieres extraer",
             font=("Segoe UI", 12, "bold"), bg=color, fg=BLANCO).pack()
    tk.Label(hdr, text="consecutivo, código, ID, nombre y apellido siempre se incluyen",
             font=("Segoe UI", 8), bg=color, fg="#e8eefc").pack(pady=(2, 0))

    cuerpo = tk.Frame(win, bg=GRIS, padx=18, pady=14)
    cuerpo.pack(fill="both", expand=True)

    disponibles = campos_disponibles(modo)
    col = 0
    fila_frame = tk.Frame(cuerpo, bg=GRIS)
    fila_frame.pack(fill="both", expand=True)

    for titulo, claves in GRUPOS_CAMPOS:
        claves_ok = [c for c in claves if c in disponibles]
        if not claves_ok:
            continue
        caja = tk.LabelFrame(fila_frame, text=f" {titulo} ", bg=BLANCO, fg=TEXTO,
                             font=("Segoe UI", 10, "bold"), padx=10, pady=6,
                             relief="solid", bd=1)
        caja.grid(row=col // 3, column=col % 3, sticky="nsew", padx=6, pady=6)
        for clave in claves_ok:
            etiqueta = CAMPOS_PAI[clave][0]
            tk.Checkbutton(caja, text=etiqueta, variable=vars_campos[clave],
                           bg=BLANCO, activebackground=BLANCO, fg=TEXTO,
                           font=("Segoe UI", 9), anchor="w",
                           cursor="hand2").pack(anchor="w")
        col += 1

    for c in range(3):
        fila_frame.columnconfigure(c, weight=1)

    # Botonera
    barra = tk.Frame(win, bg=GRIS, pady=10)
    barra.pack(fill="x")

    def marcar(valor):
        for clave in disponibles:
            vars_campos[clave].set(valor)

    def aceptar():
        on_close()
        win.destroy()

    tk.Button(barra, text="Marcar todos", font=FUENTE, bg="#e0e0e0", fg=TEXTO,
              relief="flat", padx=12, pady=4, cursor="hand2",
              command=lambda: marcar(True)).pack(side="left", padx=(20, 6))
    tk.Button(barra, text="Limpiar", font=FUENTE, bg="#e0e0e0", fg=TEXTO,
              relief="flat", padx=12, pady=4, cursor="hand2",
              command=lambda: marcar(False)).pack(side="left")
    tk.Button(barra, text="✔  Aceptar", font=("Segoe UI", 10, "bold"),
              bg=VERDE, fg=BLANCO, relief="flat", padx=18, pady=4,
              cursor="hand2", command=aceptar).pack(side="right", padx=20)

    win.update_idletasks()
    x = parent.winfo_rootx() + 40
    y = parent.winfo_rooty() + 60
    win.geometry(f"+{x}+{y}")
    win.wait_window()


# ─────────────────────────────────────────────
#  FUNCIÓN GENÉRICA DE SCRAPING — PAI
# ─────────────────────────────────────────────
def ejecutar_scraping(csv_path, opcion, modo, claves_campos,
                      barra_progreso, lbl_progreso, log_text,
                      btn_iniciar, root, crono):
    pag           = "2" if modo == "menores" else "3"
    prefijo       = "PAI_Menores_" if modo == "menores" else "PAI_Mayores_"
    nombre_opcion = NOMBRES_OPCIONES_TEXTO.get(opcion, "General")

    if opcion == "P":
        # marca de tiempo para no pisar consultas personalizadas anteriores
        archivo_salida = f"{prefijo}{nombre_opcion}_{datetime.now():%Y%m%d_%H%M}.csv"
    else:
        archivo_salida = f"{prefijo}{nombre_opcion}.csv"

    def log(msg):
        log_text.config(state="normal")
        log_text.insert(tk.END, msg + "\n")
        log_text.see(tk.END)
        log_text.config(state="disabled")

    def run():
        hora_inicio = crono.iniciar()
        try:
            log(f"🕒 Hora de inicio: {hora_inicio:%d/%m/%Y %H:%M:%S}")
            etiquetas = ", ".join(CAMPOS_PAI[c][0] for c in claves_campos) or "(sólo datos base)"
            log(f"🧩 Campos a extraer: {etiquetas}")

            if not chrome_debug_activo():
                raise RuntimeError(
                    "No hay un Chrome en modo depuración escuchando en el puerto "
                    f"{PUERTO_DEBUG}. Usa el botón «Iniciar Chrome (sesión)» y "
                    "asegúrate de haber iniciado sesión en el portal."
                )

            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"localhost:{PUERTO_DEBUG}")
            driver = webdriver.Chrome(options=options)   # Selenium Manager resuelve el driver

            entrada = pd.read_csv(csv_path, encoding="utf-8-sig", sep=None, engine="python")
            entrada.columns = (entrada.columns.str.strip()
                               .str.replace('"', '', regex=False)
                               .str.replace("'", "", regex=False))
            entrada = entrada.loc[:, ~entrada.columns.str.contains("^Unnamed")]

            log(f"✅ CSV cargado. Columnas: {entrada.columns.tolist()}")
            log(f"📋 Total de registros: {len(entrada)}")

            total      = len(entrada)
            resultados = []
            NE         = "NO ENCONTRADO"

            for index, row in entrada.iterrows():
                consecutivo = row["consecutivo"]
                codigo      = row["codigo"]

                log(f"🔍 Procesando {index + 1}/{total} — Código: {codigo}")

                try:
                    driver.get(
                        f"https://appb.saludcapital.gov.co/pai/vacunacion/datosBasicos.aspx?pag={pag}"
                    )
                    esperar_pagina_lista(driver)

                    # 1) Esperar a que el campo de búsqueda esté realmente usable
                    campo = WebDriverWait(driver, TIMEOUT).until(
                        EC.element_to_be_clickable(
                            (By.ID, "ContentPlaceHolder1_txb_NumeroIdentificacionBusqueda")
                        )
                    )
                    campo.clear()
                    campo.send_keys(str(codigo) + Keys.ENTER)

                    # 2) Esperar a que termine el postback de la búsqueda
                    try:
                        WebDriverWait(driver, TIMEOUT).until(EC.staleness_of(campo))
                    except TimeoutException:
                        pass
                    esperar_pagina_lista(driver)

                    # 3) Esperar el enlace "Seleccionar" de la grilla de resultados.
                    #    Si no aparece en TIMEOUT_CORTO, el código no existe.
                    try:
                        seleccionar_btn = WebDriverWait(driver, TIMEOUT_CORTO).until(
                            EC.element_to_be_clickable((
                                By.XPATH,
                                "//a[contains(@href,'gdvResultadoBusqueda')"
                                " and contains(@href,'Select$0')]"
                            ))
                        )
                    except TimeoutException:
                        raise NoSuchElementException(
                            f"Sin resultados en la grilla para {codigo}"
                        )

                    # 4) Clic y espera a que el formulario de detalle se reconstruya
                    click_y_esperar_postback(driver, seleccionar_btn)

                    # 5) La señal de "ya cargó": el documento tiene valor.
                    try:
                        documento = esperar_valor(
                            driver, "ContentPlaceHolder1_txb_Identificacion"
                        )
                    except TimeoutException:
                        raise NoSuchElementException(
                            f"El detalle no cargó datos para {codigo}"
                        )

                    nombre1   = leer_valor(driver, "ContentPlaceHolder1_txb_Nombre1")
                    apellido1 = leer_valor(driver, "ContentPlaceHolder1_txb_Apellido1")

                    if modo == "mayores":
                        apellido2 = leer_valor(driver, "ContentPlaceHolder1_txb_Apellido2")

                    # 6) Campos elegidos (preset o personalizados)
                    extra = extraer_campos(driver, claves_campos)

                    error = False

                except (NoSuchElementException, TimeoutException,
                        StaleElementReferenceException):
                    error     = True
                    documento = nombre1 = apellido1 = NE
                    if modo == "mayores":
                        apellido2 = NE
                    extra = {c: NE for c in claves_campos}
                    log(f"  ⚠️  Código {codigo} — NO ENCONTRADO")

                base = {"consecutivo": consecutivo, "codigo": codigo,
                        "ID": NE if error else documento,
                        "nombre1": NE if error else nombre1,
                        "apellido1": NE if error else apellido1}

                if modo == "mayores":
                    base["apellido2"] = NE if error else apellido2

                fila = {**base, **{c: (NE if error else extra[c]) for c in claves_campos}}

                resultados.append(fila)
                pd.DataFrame(resultados).to_csv(
                    archivo_salida, sep=";", index=False, encoding="utf-8-sig"
                )

                progreso = int(((index + 1) / total) * 100)
                barra_progreso["value"] = progreso
                lbl_progreso.config(
                    text=f"{index + 1} / {total} registros procesados ({progreso}%)"
                )
                root.update_idletasks()

            ini, fin, dur = crono.detener()
            log(f"\n🎉 ¡Proceso completado! Archivo guardado: {archivo_salida}")
            log(f"🕒 Inicio: {ini:%H:%M:%S}   |   Fin: {fin:%H:%M:%S}   |   "
                f"Duración: {formato_duracion(dur)}")
            messagebox.showinfo(
                "¡Listo!",
                f"Proceso completado.\nArchivo guardado como:\n{archivo_salida}\n\n"
                f"{crono.texto_resumen}"
            )

        except Exception as e:
            ini, fin, dur = crono.detener()
            log(f"\n❌ Error inesperado: {str(e)}")
            log(f"🕒 Inicio: {ini:%H:%M:%S}   |   Detenido: {fin:%H:%M:%S}   |   "
                f"Duración: {formato_duracion(dur)}")
            messagebox.showerror("Error", str(e))
        finally:
            btn_iniciar.config(state="normal")

    threading.Thread(target=run, daemon=True).start()


# ─────────────────────────────────────────────
#  OPCIONES DE EXTRACCIÓN — ADRES / COMPROBADOR
# ─────────────────────────────────────────────
OPCIONES_ADRES = [
    ("campos_tabla", "Campos de la tabla (Contributivo / BUDA)",
     "Todas las columnas que devuelve la grilla de resultados", True),
    ("tabla_origen", "Tabla de origen",
     "Indica si el registro salió de Contributivo o de BUDA", True),
    ("sexo",         "SEXO (vista de detalle)",
     "Requiere abrir el detalle de cada código — es lo más lento del proceso", True),
    ("estado",       "Estado de la consulta",
     "ENCONTRADO / NO ENCONTRADO / NO AUTORIZADO", True),
]


def filtrar_columnas(encabezados, valores, filtros):
    """Deja sólo las columnas cuyo encabezado coincide con alguno de los filtros
    escritos por el usuario (coincidencia parcial, sin distinguir mayúsculas)."""
    pares = list(zip(encabezados, valores))
    if not filtros:
        return pares
    filtros = [f.strip().lower() for f in filtros if f.strip()]
    return [(h, v) for h, v in pares
            if any(f in h.lower() for f in filtros)]


# ─────────────────────────────────────────────
#  FUNCIÓN SCRAPING — ADRES / COMPROBADOR
# ─────────────────────────────────────────────
def ejecutar_scraping_adres(csv_path, cfg, filtros_columnas,
                            barra_progreso, lbl_progreso, log_text,
                            btn_iniciar, root, crono):
    archivo_salida = "Comprobador_Tablas.xlsx"

    usar_tabla  = cfg["campos_tabla"]
    usar_origen = cfg["tabla_origen"]
    usar_sexo   = cfg["sexo"]
    usar_estado = cfg["estado"]

    def log(msg):
        log_text.config(state="normal")
        log_text.insert(tk.END, msg + "\n")
        log_text.see(tk.END)
        log_text.config(state="disabled")

    def run():
        hora_inicio = crono.iniciar()
        try:
            log(f"🕒 Hora de inicio: {hora_inicio:%d/%m/%Y %H:%M:%S}")
            elegidos = [t for k, t, _, _ in OPCIONES_ADRES if cfg[k]]
            log(f"🧩 Se extraerá: {', '.join(elegidos) if elegidos else '(nada seleccionado)'}")
            if filtros_columnas:
                log(f"🔎 Filtro de columnas: {', '.join(filtros_columnas)}")
            if not usar_sexo:
                log("⚡ Sin SEXO: no se abre el detalle, la consulta es mucho más rápida.")

            if not chrome_debug_activo():
                raise RuntimeError(
                    "No hay un Chrome en modo depuración escuchando en el puerto "
                    f"{PUERTO_DEBUG}. Usa el botón «Iniciar Chrome (sesión)» y "
                    "asegúrate de haber iniciado sesión en el portal."
                )

            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"localhost:{PUERTO_DEBUG}")
            driver = webdriver.Chrome(options=options)   # Selenium Manager resuelve el driver

            entrada = pd.read_csv(csv_path, sep=",", encoding="utf-8")
            entrada.columns = entrada.columns.str.strip()

            log(f"✅ CSV cargado. Columnas: {entrada.columns.tolist()}")
            log(f"📋 Total de registros: {len(entrada)}")

            total      = len(entrada)
            resultados = []

            driver.get("https://appb.saludcapital.gov.co/comprobadordederechos/Consulta.aspx")

            for index, row in entrada.iterrows():
                consecutivo = row["consecutivo"] if "consecutivo" in entrada.columns else index + 1
                codigo      = row["codigo"]

                log(f"🔍 Procesando {index + 1}/{total} — Código: {codigo}")

                resultado    = {"consecutivo": consecutivo, "codigo": codigo}
                intentos     = 0
                max_intentos = 3 if usar_sexo else 1
                listo        = False

                while intentos < max_intentos and not listo:
                    intentos += 1
                    try:
                        campo = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "MainContent_txtNoId"))
                        )
                        campo.clear()
                        campo.send_keys(str(codigo))
                        campo.send_keys(Keys.ENTER)
                        time.sleep(2)

                        tabla        = None
                        tabla_origen = None

                        try:
                            tabla = WebDriverWait(driver, 2).until(
                                EC.presence_of_element_located((By.ID, "MainContent_grdContributivo"))
                            )
                            tabla_origen = "Contributivo"
                        except TimeoutException:
                            try:
                                tabla = WebDriverWait(driver, 2).until(
                                    EC.presence_of_element_located((By.ID, "MainContent_grdBUDA"))
                                )
                                tabla_origen = "BUDA"
                            except TimeoutException:
                                tabla = None

                        if not tabla:
                            if usar_estado:
                                resultado["estado"] = "NO ENCONTRADO"
                            log(f"  ⚠️  Código {codigo} — NO ENCONTRADO")
                            break

                        if usar_tabla:
                            encabezados = [th.text.strip() for th in tabla.find_elements(By.TAG_NAME, "th")]
                            fila_datos  = tabla.find_elements(By.XPATH, ".//tr[2]/td")
                            valores     = [td.text.strip() for td in fila_datos]
                            for h, v in filtrar_columnas(encabezados, valores, filtros_columnas):
                                resultado[h] = v

                        if usar_origen:
                            resultado["tabla_origen"] = tabla_origen

                        # Si no piden SEXO, no hace falta entrar al detalle
                        if not usar_sexo:
                            if usar_estado:
                                resultado["estado"] = "ENCONTRADO"
                            listo = True
                            break

                        try:
                            if tabla_origen == "Contributivo":
                                link_detalle = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, \"grdContributivo','Select$0\")]"))
                                )
                            else:
                                link_detalle = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, \"grdSubsidiado','Select$0\")]"))
                                )

                            link_detalle.click()
                            time.sleep(3)

                            if "NoAutorizado.aspx" in driver.current_url:
                                log(f"  ⚠️  Código {codigo} — No autorizado (intento {intentos}). Reintentando...")
                                try:
                                    inicio_btn = WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable((By.ID, "MainContent_cmdInicio"))
                                    )
                                    inicio_btn.click()
                                    time.sleep(2)
                                    continue
                                except TimeoutException:
                                    log("  ⚠️  No se encontró el botón 'Inicio'.")
                                    break

                            sexo = WebDriverWait(driver, 2).until(
                                EC.presence_of_element_located((By.ID, "MainContent_lblSexo"))
                            ).text.strip()

                            resultado["SEXO"] = sexo
                            listo             = True
                            if usar_estado:
                                resultado["estado"] = "ENCONTRADO"

                        except TimeoutException:
                            log("  ⚠️  No se pudo extraer el campo SEXO.")
                            resultado["SEXO"] = "NO DISPONIBLE"
                            break

                    except Exception as e:
                        if usar_estado:
                            resultado["estado"] = "NO ENCONTRADO"
                        log(f"  ❌ Error con código {codigo}: {e}")
                        break

                if usar_sexo and not listo and "SEXO" not in resultado:
                    resultado["SEXO"] = "NO AUTORIZADO"
                    if usar_estado:
                        resultado["estado"] = "NO AUTORIZADO"

                # Volver a nueva consulta
                try:
                    nueva_btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.ID, "MainContent_cmdNuevaConsulta"))
                    )
                    nueva_btn.click()
                    time.sleep(2)
                except TimeoutException:
                    try:
                        nue_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.ID, "MainContent_cmdNueConsulta"))
                        )
                        nue_btn.click()
                        time.sleep(2)
                    except TimeoutException:
                        log("  ⚠️  No se encontró botón de nueva consulta.")

                resultados.append(resultado)

                # Guardado parcial
                salida_parcial = pd.DataFrame(resultados)
                try:
                    salida_parcial.to_excel(archivo_salida, index=False)
                except Exception:
                    salida_parcial.to_csv(
                        "Comprobador_Tablas.csv", index=False, encoding="utf-8-sig"
                    )

                progreso = int(((index + 1) / total) * 100)
                barra_progreso["value"] = progreso
                lbl_progreso.config(
                    text=f"{index + 1} / {total} registros procesados ({progreso}%)"
                )
                root.update_idletasks()

            # Exportación final
            salida = pd.DataFrame(resultados)
            ini, fin, dur = crono.detener()
            resumen_tiempo = (f"🕒 Inicio: {ini:%H:%M:%S}   |   Fin: {fin:%H:%M:%S}   |   "
                              f"Duración: {formato_duracion(dur)}")
            try:
                salida.to_excel(archivo_salida, index=False)
                log(f"\n🎉 ¡Proceso completado! Archivo guardado: {archivo_salida}")
                log(resumen_tiempo)
                messagebox.showinfo("¡Listo!",
                                    f"Proceso completado.\nArchivo: {archivo_salida}\n\n"
                                    f"{crono.texto_resumen}")
            except Exception:
                salida.to_csv("Comprobador_Tablas.csv", index=False, encoding="utf-8-sig")
                log("\n🎉 ¡Proceso completado! Guardado como Comprobador_Tablas.csv")
                log(resumen_tiempo)
                messagebox.showinfo("¡Listo!",
                                    "Proceso completado.\nArchivo: Comprobador_Tablas.csv\n\n"
                                    f"{crono.texto_resumen}")

        except Exception as e:
            ini, fin, dur = crono.detener()
            log(f"\n❌ Error inesperado: {str(e)}")
            log(f"🕒 Inicio: {ini:%H:%M:%S}   |   Detenido: {fin:%H:%M:%S}   |   "
                f"Duración: {formato_duracion(dur)}")
            messagebox.showerror("Error", str(e))
        finally:
            btn_iniciar.config(state="normal")

    threading.Thread(target=run, daemon=True).start()


# ─────────────────────────────────────────────
#  VENTANA PAI (Menores / Mayores)
# ─────────────────────────────────────────────
def abrir_formulario(modo):
    ventana = tk.Toplevel(root_selector)
    ventana.title(
        f"Sistema de Consulta PAI — {'Menores' if modo == 'menores' else 'Mayores'}"
    )
    ventana.geometry("760x1000")
    ventana.resizable(False, True)
    ventana.configure(bg=GRIS)

    COLOR_HEADER = AZUL if modo == "menores" else NARANJA
    LABEL_MODO   = "👶  PAI Menores" if modo == "menores" else "🧑  PAI Mayores"
    SUB_MODO     = "Consulta de menores de edad — pág. 2" if modo == "menores" \
                   else "Consulta de mayores de edad — pág. 3"

    frame_header = tk.Frame(ventana, bg=COLOR_HEADER, pady=14)
    frame_header.pack(fill="x")
    tk.Label(frame_header, text=f"🏥  Sistema de Consulta PAI  |  {LABEL_MODO}",
             font=("Segoe UI", 14, "bold"), bg=COLOR_HEADER, fg=BLANCO).pack()
    tk.Label(frame_header, text=SUB_MODO,
             font=("Segoe UI", 9), bg=COLOR_HEADER,
             fg="#ffe0c8" if modo == "mayores" else "#c8d8f8").pack()

    fm = tk.Frame(ventana, bg=GRIS, padx=24, pady=16)
    fm.pack(fill="both", expand=True)

    # Archivo CSV
    tk.Label(fm, text="📁  Configuración de archivos", font=FUENTE_T,
             bg=GRIS, fg=AZUL_OSC).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

    entry_csv = tk.Entry(fm, width=46, font=FUENTE, relief="solid", bd=1)
    entry_csv.grid(row=1, column=1, padx=6, pady=4)
    entry_csv.insert(0, "codigos.csv")
    tk.Label(fm, text="Archivo CSV de códigos:", font=FUENTE, bg=GRIS, fg=TEXTO).grid(row=1, column=0, sticky="w")
    tk.Button(fm, text="📂 Buscar", font=FUENTE, bg=COLOR_HEADER, fg=BLANCO,
              relief="flat", padx=8, cursor="hand2",
              command=lambda: [entry_csv.delete(0, tk.END),
                               entry_csv.insert(0, filedialog.askopenfilename(filetypes=[("CSV", "*.csv")]) or entry_csv.get())]
              ).grid(row=1, column=2)

    # Navegador de trabajo (sesión autenticada)
    frame_nav = tk.Frame(fm, bg=GRIS)
    frame_nav.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 2))
    lbl_estado_chrome = tk.Label(frame_nav, text="", font=("Segoe UI", 9),
                                 bg=GRIS, fg="#555555", anchor="w")

    def revisar_chrome():
        if chrome_debug_activo():
            lbl_estado_chrome.config(text="✅ Chrome de trabajo activo.", fg=VERDE_OSC)
        else:
            lbl_estado_chrome.config(
                text="⚠️ Sin navegador de trabajo. Ábrelo antes de consultar.",
                fg=NARANJA_OSC)

    def abrir_chrome():
        ok, msg = lanzar_chrome_debug()
        revisar_chrome()
        (messagebox.showinfo if ok else messagebox.showerror)("Navegador", msg)

    tk.Button(frame_nav, text="🌐  Iniciar Chrome (sesión)", font=("Segoe UI", 10, "bold"),
              bg=COLOR_HEADER, fg=BLANCO, relief="flat", padx=14, pady=5,
              cursor="hand2", command=abrir_chrome).pack(side="left")
    tk.Button(frame_nav, text="⟳", font=("Segoe UI", 10, "bold"), bg="#e0e0e0",
              fg=TEXTO, relief="flat", padx=10, pady=5, cursor="hand2",
              command=revisar_chrome).pack(side="left", padx=6)
    lbl_estado_chrome.pack(side="left", padx=(6, 0))
    revisar_chrome()

    ttk.Separator(fm, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=12)

    tk.Label(fm, text="🔎  Selecciona el tipo de consulta", font=FUENTE_T,
             bg=GRIS, fg=AZUL_OSC).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 8))

    opcion_var     = tk.StringVar(value="1")
    lista_opciones = OPCIONES_MENORES if modo == "menores" else OPCIONES_MAYORES

    for i, (val, titulo, desc) in enumerate(lista_opciones):
        frame_op = tk.Frame(fm, bg=BLANCO, relief="solid", bd=1, padx=10, pady=6)
        frame_op.grid(row=5 + i, column=0, columnspan=3, sticky="ew", pady=3)
        frame_op.columnconfigure(1, weight=1)
        tk.Radiobutton(frame_op, variable=opcion_var, value=val, bg=BLANCO,
                       activebackground=BLANCO, cursor="hand2").grid(row=0, column=0, rowspan=2)
        tk.Label(frame_op, text=f"  {val}.  {titulo}", font=("Segoe UI", 10, "bold"),
                 bg=BLANCO, fg=TEXTO, anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(frame_op, text=f"      {desc}", font=("Segoe UI", 8),
                 bg=BLANCO, fg="#666666", anchor="w").grid(row=1, column=1, sticky="w")

    # ── Opción PERSONALIZADA ──
    fila_pers   = 5 + len(lista_opciones)
    vars_campos = {c: tk.BooleanVar(value=False) for c in campos_disponibles(modo)}

    frame_pers = tk.Frame(fm, bg=BLANCO, relief="solid", bd=1, padx=10, pady=6)
    frame_pers.grid(row=fila_pers, column=0, columnspan=3, sticky="ew", pady=3)
    frame_pers.columnconfigure(1, weight=1)
    tk.Radiobutton(frame_pers, variable=opcion_var, value="P", bg=BLANCO,
                   activebackground=BLANCO, cursor="hand2").grid(row=0, column=0, rowspan=3)
    tk.Label(frame_pers, text="  P.  Personalizada", font=("Segoe UI", 10, "bold"),
             bg=BLANCO, fg=VERDE_OSC, anchor="w").grid(row=0, column=1, sticky="w")
    tk.Label(frame_pers, text="      Arma tu propia combinación (p. ej. sólo teléfono y dirección)",
             font=("Segoe UI", 8), bg=BLANCO, fg="#666666", anchor="w").grid(row=1, column=1, sticky="w")

    lbl_resumen = tk.Label(frame_pers, text="      Ningún campo seleccionado todavía.",
                           font=("Segoe UI", 8, "italic"), bg=BLANCO, fg="#888888",
                           anchor="w", wraplength=520, justify="left")
    lbl_resumen.grid(row=2, column=1, sticky="w", pady=(2, 0))

    def refrescar_resumen():
        elegidos = [CAMPOS_PAI[c][0] for c in vars_campos if vars_campos[c].get()]
        if elegidos:
            lbl_resumen.config(
                text=f"      {len(elegidos)} campo(s): " + ", ".join(elegidos),
                fg=VERDE_OSC)
        else:
            lbl_resumen.config(text="      Ningún campo seleccionado todavía.",
                               fg="#888888")

    def personalizar():
        opcion_var.set("P")
        abrir_selector_campos(ventana, modo, vars_campos, COLOR_HEADER,
                              lbl_resumen, refrescar_resumen)

    tk.Button(frame_pers, text="⚙  Elegir campos…", font=("Segoe UI", 9, "bold"),
              bg=VERDE, fg=BLANCO, relief="flat", padx=10, pady=3, cursor="hand2",
              command=personalizar).grid(row=0, column=2, rowspan=3, padx=(8, 0))

    fila_sep2 = fila_pers + 1
    ttk.Separator(fm, orient="horizontal").grid(
        row=fila_sep2, column=0, columnspan=3, sticky="ew", pady=12
    )

    barra_progreso = ttk.Progressbar(fm, orient="horizontal", length=680, mode="determinate")
    lbl_progreso   = tk.Label(fm, text="En espera...", font=("Segoe UI", 9), bg=GRIS, fg="#555555")
    lbl_tiempos    = tk.Label(fm, text="", font=("Segoe UI", 9, "bold"),
                              bg=GRIS, fg=AZUL_OSC)
    log_text       = tk.Text(fm, height=7, width=84, font=("Consolas", 9),
                             bg="#1e1e1e", fg="#00e676", relief="flat", state="disabled")

    crono = Cronometro(ventana, lbl_tiempos)

    def iniciar():
        csv_p = entry_csv.get()
        opc   = opcion_var.get()
        if not csv_p or not opc:
            messagebox.showwarning("Campos incompletos", "Por favor completa todos los campos.")
            return

        if not chrome_debug_activo():
            messagebox.showwarning(
                "Sin navegador de trabajo",
                "Primero abre el navegador con «🌐 Iniciar Chrome (sesión)» "
                "e inicia sesión en el portal."
            )
            return

        if opc == "P":
            claves = [c for c in vars_campos if vars_campos[c].get()]
            if not claves:
                messagebox.showwarning(
                    "Sin campos",
                    "Seleccionaste la consulta personalizada pero no marcaste ningún campo.\n\n"
                    "Usa el botón «⚙ Elegir campos…» para escoger, por ejemplo, "
                    "Teléfono 1, Teléfono 2 y Dirección."
                )
                return
        else:
            claves = [c for c in PRESETS_CAMPOS.get(opc, [])
                      if c in vars_campos]   # filtra madre en mayores

        btn_iniciar.config(state="disabled")
        barra_progreso["value"] = 0
        log_text.config(state="normal")
        log_text.delete("1.0", tk.END)
        log_text.config(state="disabled")
        ejecutar_scraping(csv_p, opc, modo, claves,
                          barra_progreso, lbl_progreso, log_text,
                          btn_iniciar, ventana, crono)

    btn_iniciar = tk.Button(fm, text="▶  INICIAR CONSULTA",
                            font=("Segoe UI", 11, "bold"),
                            bg=VERDE, fg=BLANCO, relief="flat",
                            padx=20, pady=8, cursor="hand2",
                            command=iniciar)
    btn_iniciar.grid(row=fila_sep2 + 1, column=0, columnspan=3, pady=4)
    barra_progreso.grid(row=fila_sep2 + 2, column=0, columnspan=3, pady=(10, 2))
    lbl_progreso.grid(row=fila_sep2 + 3, column=0, columnspan=3)
    lbl_tiempos.grid(row=fila_sep2 + 4, column=0, columnspan=3, pady=(4, 0))
    tk.Label(fm, text="📋  Registro de actividad:", font=FUENTE_T,
             bg=GRIS, fg=AZUL_OSC).grid(row=fila_sep2 + 5, column=0, columnspan=3, sticky="w", pady=(10, 4))
    log_text.grid(row=fila_sep2 + 6, column=0, columnspan=3)

    tk.Label(ventana, text="© 2026 LUIS SILVA — SISVAN  |  Secretaría Distrital de Salud",
             font=("Segoe UI", 8), bg="#d0d8e4", fg="#555555", pady=6).pack(fill="x", side="bottom")


# ─────────────────────────────────────────────
#  VENTANA ADRES / COMPROBADOR DE DERECHOS
# ─────────────────────────────────────────────
def abrir_formulario_adres():
    ventana = tk.Toplevel(root_selector)
    ventana.title("Sistema de Consulta — ADRES / Comprobador de Derechos")
    ventana.geometry("760x860")
    ventana.resizable(False, True)
    ventana.configure(bg=GRIS)

    # Encabezado
    frame_header = tk.Frame(ventana, bg=MORADO, pady=14)
    frame_header.pack(fill="x")
    tk.Label(frame_header, text="🏥  Sistema de Consulta  |  🔐  ADRES / Comprobador",
             font=("Segoe UI", 14, "bold"), bg=MORADO, fg=BLANCO).pack()
    tk.Label(frame_header, text="Verificación de derechos — Régimen Contributivo y BUDA",
             font=("Segoe UI", 9), bg=MORADO, fg="#e1c6f5").pack(pady=(2, 0))

    fm = tk.Frame(ventana, bg=GRIS, padx=24, pady=16)
    fm.pack(fill="both", expand=True)

    # Archivo CSV
    tk.Label(fm, text="📁  Configuración de archivos", font=FUENTE_T,
             bg=GRIS, fg=AZUL_OSC).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

    entry_csv = tk.Entry(fm, width=46, font=FUENTE, relief="solid", bd=1)
    entry_csv.grid(row=1, column=1, padx=6, pady=4)
    entry_csv.insert(0, "codigos.csv")
    tk.Label(fm, text="Archivo CSV de códigos:", font=FUENTE, bg=GRIS, fg=TEXTO).grid(row=1, column=0, sticky="w")
    tk.Button(fm, text="📂 Buscar", font=FUENTE, bg=MORADO, fg=BLANCO,
              relief="flat", padx=8, cursor="hand2",
              command=lambda: [entry_csv.delete(0, tk.END),
                               entry_csv.insert(0, filedialog.askopenfilename(filetypes=[("CSV", "*.csv")]) or entry_csv.get())]
              ).grid(row=1, column=2)

    # Navegador de trabajo (sesión autenticada)
    frame_nav = tk.Frame(fm, bg=GRIS)
    frame_nav.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 2))
    lbl_estado_chrome = tk.Label(frame_nav, text="", font=("Segoe UI", 9),
                                 bg=GRIS, fg="#555555", anchor="w")

    def revisar_chrome():
        if chrome_debug_activo():
            lbl_estado_chrome.config(text="✅ Chrome de trabajo activo.", fg=VERDE_OSC)
        else:
            lbl_estado_chrome.config(
                text="⚠️ Sin navegador de trabajo. Ábrelo antes de consultar.",
                fg=NARANJA_OSC)

    def abrir_chrome():
        ok, msg = lanzar_chrome_debug()
        revisar_chrome()
        (messagebox.showinfo if ok else messagebox.showerror)("Navegador", msg)

    tk.Button(frame_nav, text="🌐  Iniciar Chrome (sesión)", font=("Segoe UI", 10, "bold"),
              bg=MORADO, fg=BLANCO, relief="flat", padx=14, pady=5,
              cursor="hand2", command=abrir_chrome).pack(side="left")
    tk.Button(frame_nav, text="⟳", font=("Segoe UI", 10, "bold"), bg="#e0e0e0",
              fg=TEXTO, relief="flat", padx=10, pady=5, cursor="hand2",
              command=revisar_chrome).pack(side="left", padx=6)
    lbl_estado_chrome.pack(side="left", padx=(6, 0))
    revisar_chrome()

    ttk.Separator(fm, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=12)

    # ── Personalización de la extracción ──
    tk.Label(fm, text="🔎  Personaliza qué se extrae por cada código", font=FUENTE_T,
             bg=GRIS, fg=AZUL_OSC).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 6))

    frame_info = tk.Frame(fm, bg=BLANCO, relief="solid", bd=1, padx=14, pady=10)
    frame_info.grid(row=5, column=0, columnspan=3, sticky="ew", pady=4)

    vars_adres = {}
    for clave, titulo, desc, por_defecto in OPCIONES_ADRES:
        vars_adres[clave] = tk.BooleanVar(value=por_defecto)
        fila = tk.Frame(frame_info, bg=BLANCO)
        fila.pack(fill="x", anchor="w", pady=1)
        tk.Checkbutton(fila, text=titulo, variable=vars_adres[clave],
                       font=("Segoe UI", 10, "bold"), bg=BLANCO, fg=TEXTO,
                       activebackground=BLANCO, cursor="hand2").pack(anchor="w")
        tk.Label(fila, text=f"        {desc}", font=("Segoe UI", 8),
                 bg=BLANCO, fg="#666666").pack(anchor="w")

    # Filtro de columnas de la tabla
    frame_filtro = tk.Frame(fm, bg=GRIS)
    frame_filtro.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 2))
    tk.Label(frame_filtro, text="Columnas específicas (opcional):",
             font=FUENTE, bg=GRIS, fg=TEXTO).pack(side="left")
    entry_cols = tk.Entry(frame_filtro, width=44, font=FUENTE, relief="solid", bd=1)
    entry_cols.pack(side="left", padx=6)
    tk.Label(fm, text="      Escribe los nombres separados por coma (ej.: EPS, Régimen, Estado). "
                      "Si lo dejas vacío se traen todas las columnas de la tabla.",
             font=("Segoe UI", 8, "italic"), bg=GRIS, fg="#888888",
             justify="left").grid(row=7, column=0, columnspan=3, sticky="w")

    tk.Label(fm, text="📄  Salida: Comprobador_Tablas.xlsx  (o .csv si falta openpyxl)",
             font=("Segoe UI", 8, "italic"), bg=GRIS, fg="#888888").grid(
        row=8, column=0, columnspan=3, sticky="w", pady=(6, 2))

    ttk.Separator(fm, orient="horizontal").grid(row=9, column=0, columnspan=3, sticky="ew", pady=10)

    barra_progreso = ttk.Progressbar(fm, orient="horizontal", length=680, mode="determinate")
    lbl_progreso   = tk.Label(fm, text="En espera...", font=("Segoe UI", 9), bg=GRIS, fg="#555555")
    lbl_tiempos    = tk.Label(fm, text="", font=("Segoe UI", 9, "bold"), bg=GRIS, fg=MORADO_OSC)
    log_text       = tk.Text(fm, height=7, width=84, font=("Consolas", 9),
                             bg="#1e1e1e", fg="#ce93d8", relief="flat", state="disabled")

    crono = Cronometro(ventana, lbl_tiempos)

    def iniciar():
        csv_p = entry_csv.get()
        if not csv_p:
            messagebox.showwarning("Campos incompletos", "Por favor completa todos los campos.")
            return

        if not chrome_debug_activo():
            messagebox.showwarning(
                "Sin navegador de trabajo",
                "Primero abre el navegador con «🌐 Iniciar Chrome (sesión)» "
                "e inicia sesión en el portal."
            )
            return

        cfg = {k: v.get() for k, v in vars_adres.items()}
        if not any(cfg.values()):
            messagebox.showwarning(
                "Sin selección",
                "Marca al menos un dato para extraer (campos de la tabla, "
                "tabla de origen, SEXO o estado)."
            )
            return

        filtros = [c.strip() for c in entry_cols.get().split(",") if c.strip()]

        btn_iniciar.config(state="disabled")
        barra_progreso["value"] = 0
        log_text.config(state="normal")
        log_text.delete("1.0", tk.END)
        log_text.config(state="disabled")
        ejecutar_scraping_adres(csv_p, cfg, filtros,
                                barra_progreso, lbl_progreso, log_text,
                                btn_iniciar, ventana, crono)

    btn_iniciar = tk.Button(fm, text="▶  INICIAR CONSULTA ADRES",
                            font=("Segoe UI", 11, "bold"),
                            bg=MORADO, fg=BLANCO, relief="flat",
                            padx=20, pady=8, cursor="hand2",
                            command=iniciar)
    btn_iniciar.grid(row=10, column=0, columnspan=3, pady=4)
    barra_progreso.grid(row=11, column=0, columnspan=3, pady=(10, 2))
    lbl_progreso.grid(row=12, column=0, columnspan=3)
    lbl_tiempos.grid(row=13, column=0, columnspan=3, pady=(4, 0))
    tk.Label(fm, text="📋  Registro de actividad:", font=FUENTE_T,
             bg=GRIS, fg=AZUL_OSC).grid(row=14, column=0, columnspan=3, sticky="w", pady=(10, 4))
    log_text.grid(row=15, column=0, columnspan=3)

    tk.Label(ventana, text="© 2026 LUIS SILVA — SISVAN  |  Secretaría Distrital de Salud",
             font=("Segoe UI", 8), bg="#d0d8e4", fg="#555555", pady=6).pack(fill="x", side="bottom")


# ─────────────────────────────────────────────
#  PANTALLA SELECTOR INICIAL
# ─────────────────────────────────────────────
root_selector = tk.Tk()
root_selector.title("Sistema de Consulta PAI / ADRES — SISVAN 2026")
root_selector.geometry("520x660")
root_selector.resizable(False, False)
root_selector.configure(bg=GRIS)

# Header
frame_hdr = tk.Frame(root_selector, bg=AZUL, pady=18)
frame_hdr.pack(fill="x")
tk.Label(frame_hdr, text="🏥  Sistema de Consulta PAI / ADRES",
         font=("Segoe UI", 16, "bold"), bg=AZUL, fg=BLANCO).pack()
tk.Label(frame_hdr, text="SISVAN 2026 — Secretaría Distrital de Salud",
         font=("Segoe UI", 9), bg=AZUL, fg="#c8d8f8").pack(pady=(2, 0))

# Cuerpo
frame_body = tk.Frame(root_selector, bg=GRIS, padx=40, pady=26)
frame_body.pack(fill="both", expand=True)

tk.Label(frame_body, text="Selecciona el módulo de consulta:",
         font=("Segoe UI", 12, "bold"), bg=GRIS, fg=TEXTO).pack(pady=(0, 20))

# ── Botón PAI Menores ──
tk.Frame(frame_body, bg=AZUL, bd=0).pack(fill="x", pady=4)
tk.Button(frame_body,
          text="👶   PAI MENORES",
          font=("Segoe UI", 13, "bold"),
          bg=AZUL, fg=BLANCO,
          relief="flat", pady=14, cursor="hand2",
          activebackground=AZUL_OSC, activeforeground=BLANCO,
          command=lambda: abrir_formulario("menores")
          ).pack(fill="x")
tk.Label(frame_body, text="Consulta de menores de edad  (pág. 2 — 5 opciones + personalizada)",
         font=("Segoe UI", 8), bg=GRIS, fg="#777777").pack(pady=(0, 4))

# Separador
tk.Frame(frame_body, bg="#cccccc", height=1).pack(fill="x", pady=10)

# ── Botón PAI Mayores ──
tk.Button(frame_body,
          text="🧑   PAI MAYORES",
          font=("Segoe UI", 13, "bold"),
          bg=NARANJA, fg=BLANCO,
          relief="flat", pady=14, cursor="hand2",
          activebackground=NARANJA_OSC, activeforeground=BLANCO,
          command=lambda: abrir_formulario("mayores")
          ).pack(fill="x")
tk.Label(frame_body, text="Consulta de mayores de edad  (pág. 3 — 4 opciones + personalizada)",
         font=("Segoe UI", 8), bg=GRIS, fg="#777777").pack(pady=(0, 4))

# Separador
tk.Frame(frame_body, bg="#cccccc", height=1).pack(fill="x", pady=10)

# ── Botón ADRES ──
tk.Button(frame_body,
          text="🔐   ADRES / COMPROBADOR DE DERECHOS",
          font=("Segoe UI", 13, "bold"),
          bg=MORADO, fg=BLANCO,
          relief="flat", pady=14, cursor="hand2",
          activebackground=MORADO_OSC, activeforeground=BLANCO,
          command=abrir_formulario_adres
          ).pack(fill="x")
tk.Label(frame_body, text="Verificación de derechos — Contributivo y BUDA  (extracción personalizable)",
         font=("Segoe UI", 8), bg=GRIS, fg="#777777").pack(pady=(0, 4))

# Footer
tk.Label(root_selector,
         text="© 2026 LUIS SILVA — SISVAN  |  Secretaría Distrital de Salud",
         font=("Segoe UI", 8), bg="#d0d8e4", fg="#555555", pady=6).pack(fill="x", side="bottom")

root_selector.mainloop()
