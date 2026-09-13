# ⚽ Sport-Vivo — Proxy IPTV Inteligente con Failover y EPG

Stack completo y automatizado para desplegar tu propio proxy y gestor de streaming IPTV deportivo en casa con **Docker** (optimizado para **macOS / OrbStack** y **Linux**), basado en **Dispatcharr**.

Permite intermediar tu proveedor IPTV (vía Xtream Codes / M3U), proteger estrictamente el límite de conexiones simultáneas, alternar automáticamente entre señales de respaldo (**failover**) si una transmisión se interrumpe durante un partido, e inyectar una guía de programación real (**EPG**) con logos oficiales para **TiviMate**, **Smart TVs** y **Jellyfin**.

---

## 🌟 Características Principales

- 🛡️ **Protección de Conexión Única (Connection Pool)**: Dispatcharr centraliza el acceso hacia el proveedor (ej. Trex OTT). Si tu cuenta tiene un límite estricto de **1 conexión simultánea**, el proxy garantiza que nunca se exceda, evitando baneos o cortes de servicio.
- ⚡ **Failover Automático Transparente**: Cada canal deportivo tiene asignados múltiples streams en orden de prioridad (ej. `1: RAW 1080p 60fps`, `2: Backup HD`). Si el stream principal se congela o sufre buffering, el proxy conmuta al secundario de forma transparente para el reproductor.
- 🎯 **Curaduría Deportiva Argentina**: Canales organizados y ordenados exclusivamente con el **Pack Fútbol** (ESPN Premium, TNT Sports, TyC Sports), la señal completa de **Fox Sports**, la suite **ESPN** y las señales de **DSports (DirecTV Sports)** para copas internacionales.
- 📅 **EPG y Grilla Real Integrada**: Guía de programación electrónica vinculada con XMLTV argentino actualizado automáticamente, mostrando los eventos y partidos reales de la Liga Profesional y torneos continentales.
- 🔌 **Emulación Nativa de Xtream Codes API**: Expone endpoints compatibles con TiviMate, IPTV Smarters o Televizo para iniciar sesión fácilmente con usuario y contraseña sin necesidad de manipular URLs M3U extensas.
- 🍿 **Integración con Jellyfin (Live TV)**: Conectado a la red interna de Docker (`media-net`), permitiendo a Jellyfin consumir la lista y la guía XMLTV como sintonizador de televisión en vivo.

---

## 📐 Arquitectura

```mermaid
flowchart TD
    subgraph Proveedor ["Proveedor IPTV Externo"]
        Trex["Trex OTT (Xtream Codes)"]
        EPGExt["Fuente XMLTV Argentina (GZ)"]
    end

    subgraph Host ["Entorno Docker / OrbStack"]
        subgraph SportVivo ["sport-vivo (Dispatcharr AIO :9191)"]
            Proxy["Proxy de Conexión (Pool 1 Stream)"]
            Failover["Motor de Failover (Stream 1 ➔ Stream 2)"]
            DB[(PostgreSQL / SQLite & Redis)]
            API["Xtream Codes & M3U/XMLTV Server"]
        end
        
        subgraph MediaNet ["Red Compartida Docker (media-net)"]
            JF["Jellyfin :8096 (Live TV Tuner)"]
        end
    end

    subgraph Clientes ["Dispositivos de Reproducción"]
        TV["TiviMate / Smart TV (Chromecast, Shield, etc.)"]
        WebJF["Jellyfin Web / Apps"]
    end

    Trex -->|Streams RAW / HD| Proxy
    EPGExt -->|Guía y Logos| DB
    Proxy --> Failover
    Failover --> API

    API -->|Xtream Codes API / M3U / EPG| TV
    API -.->|M3U / XMLTV interno (media-net)| JF
    JF --> WebJF
```

---

## 📺 Canales Curados y Mapeo de Failover

| Nº | Canal | Señal Principal (P1) | Señal Backup (P2) | EPG (tvg-id) |
| :---: | :--- | :--- | :--- | :--- |
| **01** | **ESPN Premium** | ARG: ESPN PREMIUM RAW | VO: FOX SPORTS PREMIUM ARG HD | `a1ty` |
| **02** | **TNT Sports** | ARG: TNT SPORTS RAW | VO: TNT SPORTS ARG HD | `a1sm` |
| **03** | **TyC Sports** | ARG: TYC SPORTS RAW | ARG: TYC SPORTS RAW Alt | `a1sk` |
| **04** | **Fox Sports 1** | ARG: FOX SPORTS 1 RAW | VO: FOX SPORTS 1 ARG HD | `a1tx` |
| **05** | **Fox Sports 2** | ARG: FOX SPORTS 2 RAW | — | `a1r3` |
| **06** | **Fox Sports 3** | ARG: FOX SPORTS 3 RAW | — | `a1sl` |
| **07** | **ESPN** | ARG: ESPN RAW | VO: PN ARG HD | `a1jl` |
| **08** | **ESPN 2** | ARG: ESPN 2 RAW | VO: PN 2 ARG HD | `a1jc` |
| **09** | **ESPN 3** | ARG: ESPN 3 RAW | VO: PN 3 ARG HD | `a1kf` |
| **10** | **ESPN Extra** | ARG: ESPN EXTRA RAW | VO: PN+ ARG HD | `a1j1` |
| **11** | **DSports (DirecTV 1)** | CO: DIRECTV SPORTS 1 | RC: DIRECTV SPORTS HD | — |
| **12** | **DSports 2** | CO: DIRECTV SPORTS 2 | RC: DIRECTV SPORTS 2 | — |
| **13** | **DSports+ / DTV** | ARG: DTV RAW | — | — |

---

## 🚀 Inicio Rápido

### 1. Clonar el repositorio

```bash
git clone https://github.com/gustavosz/sport-vivo.git
cd sport-vivo
```

### 2. Configurar variables de entorno

Copia la plantilla `.env.example`:

```bash
cp .env.example .env
```

Edita `.env` con los datos de tu red y credenciales de IPTV:

```env
# --- Configuración de Red ---
DISPATCHARR_PORT=9191
HOST_IP=192.168.1.50
DOCKER_NETWORK=media-net
DISPATCHARR_LOG_LEVEL=info
DISPATCHARR_DATA_DIR=./data

# --- Administrador Dispatcharr ---
ADMIN_USERNAME=admin
ADMIN_PASSWORD="TuPasswordAdmin123*"

# --- Cliente IPTV (TiviMate / Jellyfin) ---
CLIENT_USERNAME=tv_living
CLIENT_PASSWORD="TuPasswordCliente123*"

# --- Proveedor IPTV (Xtream Codes) ---
PROVIDER_NAME="Trex OTT - Deportes AR"
PROVIDER_SERVER_URL="http://pro.business-cdn-8k.com"
PROVIDER_USERNAME="tu_usuario_iptv"
PROVIDER_PASSWORD="tu_password_iptv"
PROVIDER_MAX_STREAMS=1

# --- Guía EPG ---
EPG_NAME="EPG Argentina"
EPG_URL="https://jarap.github.io/iptv-epg-argentina/epg.xml.gz"
```

### 3. Levantar el stack

Ejecuta el script automatizado o usa el Makefile:

```bash
make up
# o directamente: ./scripts/start.sh
```

El script se encargará automáticamente de:
1. Verificar o crear la red externa de Docker (`media-net`).
2. Levantar el contenedor `dispatcharr` con persistencia en `./data`.
3. Esperar que el servidor web responda.
4. Ejecutar el aprovisionamiento idempotente (usuarios, proveedor, canales con failover y EPG).
5. Imprimir en pantalla las credenciales y URLs listas para copiar.

---

## 🛠️ Comandos Disponibles

El proyecto incluye un `Makefile` para facilitar la administración:

| Comando | Descripción |
| :--- | :--- |
| `make up` | Inicia el stack y ejecuta la sincronización de canales y EPG |
| `make down` | Detiene y remueve los contenedores limpiamente |
| `make restart` | Reinicia todo el servicio |
| `make logs` | Visualiza los logs en tiempo real de Dispatcharr |
| `make status` | Muestra el estado del contenedor |
| `make provision` | Vuelve a sincronizar canales, failover y EPG sin reiniciar |

---

## 📱 Configuración en Reproductores

### Configuración en TiviMate (Recomendado)

1. Abre **TiviMate** en tu Smart TV o TV Box.
2. Selecciona **Agregar lista de reproducción** ➔ **Códigos Xtream (Xtream Codes)**.
3. Ingresa los siguientes datos:
   - **Dirección del servidor**: `http://<IP_DE_TU_PC>:9191` *(ej: `http://192.168.1.50:9191`)*
   - **Nombre de usuario**: El valor de `CLIENT_USERNAME` *(ej: `tv_living`)*
   - **Contraseña**: El valor de `CLIENT_PASSWORD`
4. Marca la opción **Incluir canales de TV**.
5. ¡Listo! La lista cargará directamente el grupo `Deportes Argentina` con su guía EPG sincronizada.

---

### Configuración en Jellyfin (Live TV / TV en Directo)

Dado que Dispatcharr está conectado a la misma red externa de Docker (`media-net`), puedes integrarlo sin salir del entorno virtual:

1. Ingresa al panel de administración de Jellyfin: **Panel de Control** ➔ **TV en Directo (Live TV)**.
2. En **Sintonizadores de TV**, haz clic en **+** y selecciona **M3U Playlist**:
   - **Ruta de archivo o URL**:
     ```text
     http://dispatcharr:9191/output/m3u?username=tv_living&password=TuPasswordCliente123*
     ```
3. En **Proveedores de guía de TV**, haz clic en **+** y selecciona **XMLTV**:
   - **Ruta de archivo o URL**:
     ```text
     http://dispatcharr:9191/output/epg?username=tv_living&password=TuPasswordCliente123*
     ```
4. Guarda y actualiza la guía. Los canales aparecerán en la sección "En Directo" de Jellyfin.

---

## 🔒 Seguridad y Persistencia

- **Archivos Sensibles**: Las credenciales reales en `.env` y los datos de base de datos en `./data/` están excluidos del control de versiones a través de `.gitignore`.
- **Persistencia**: Toda la configuración de Dispatcharr se almacena localmente en la carpeta `./data/`, permitiendo actualizaciones de imagen (`docker compose pull`) sin perder datos.

---

## 📄 Licencia

MIT License — Libre para uso personal y modificación en entornos homelab.
