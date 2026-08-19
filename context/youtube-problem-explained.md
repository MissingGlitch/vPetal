# ¿Cómo funciona la extracción de audio de youtube con yt-dlp? Limitaciones y estado actual (agosto 2026)

## 1. Contexto de la situación actual

Extraer el audio de un video de youtube usando `yt-dlp` o cualquier otra alternativa **ya no es una operación trivial de "pegar una URL y listo"**. Desde mediados de 2025, YouTube ha desplegado progresivamente dos mecanismos anti-bot independientes (**Resolución con JavaScript** y los **PO Token**) que, combinados, hacen que casi cualquier forma de extracción automática esté sujeta a alguna restricción. Este documento explica ambos mecanismos, cómo interactúan entre sí, y qué opciones reales existen hoy para cualquier proyecto que quiera usar `yt-dlp` como dependencia; como es el caso de vPetal como bot de discord que pretende reproducir música de links de youtube.

## 2. ¿Qué es un "cliente" de YouTube en yt-dlp?

YouTube no responde igual a todo el mundo: su API interna (**Innertube**) identifica desde cuál "dispositivo" se hace la petición (navegador web, app de Android, app de iOS, dispositivo VR, etc.) y le entrega datos/formatos distintos según ese perfil. yt-dlp es capaz de simular estas identidades mediante **"clientes"**.

Ejemplos de clientes definidos en yt-dlp: `web`, `web_safari`, `web_embedded`, `web_music`, `mweb`, `android`, `android_vr`, `ios`, `visionos`, `tv`, etc. Cada uno debe cumplir sus propias reglas de seguridad para poder obtener formatos de audio/video descargables que entrega YouTube.

## 3. Los dos mecanismos anti-bot que hay que superar

### 3.1. Resolución con JavaScript (firma cifrada y "n challenge")

Cuando un navegador real reproduce un video, ejecuta JavaScript propio de YouTube para descifrar la URL del stream (`signatureCipher`) y resolver el llamado **"n challenge"**. yt-dlp, al no ser un navegador, necesita un **runtime de JavaScript externo** (Deno, Node.js, Bun o QuickJS) junto con el proyecto complementario `yt-dlp-ejs` para replicar esto.

Si no hay runtime disponible, yt-dlp descarta automáticamente los clientes que dependen de JS para no fallar directamente.

### 3.2. PO Token (Proof of Origin Token)

El **PO Token** es un mecanismo *distinto* al anterior: Es un token que YouTube exige a ciertos clientes para probar que la petición viene de un dispositivo/app "genuina" y no de un script. Este token se genera mediante un proceso de "attestation" (BotGuard en Web, DroidGuard en Android, iOSGuard en iOS) que **yt-dlp no puede generar por sí mismo** por lo que debe obtenerse externamente, típicamente mediante un plugin "PO Token Provider".

Si el token requerido no se proporciona, yt-dlp descarta el formato.

## 4. Lista de Clientes vs JS Runtime / PO Token

Revisando la configuración real de los clientes más relevantes, se observa un patrón consistente y documentado por el propio proyecto (tabla oficial de la wiki de yt-dlp):

| Cliente | ¿Necesita JS Runtime? | ¿Necesita PO Token? |
|---|---|---|
| `web` | Sí | Sí (Subs, GVS) — solo formatos SABR sin él |
| `web_safari` | Sí | Sí, salvo HLS |
| `mweb` | Sí | Sí (GVS) |
| `web_embedded` | Sí | No requerido, pero solo videos "embebibles" |
| `web_music` | Sí | Sí (GVS) |
| `android` | No (`REQUIRE_JS_PLAYER: False`) | Sí (GVS o Player) |
| `android_vr` | No | Sí para HTTPS/DASH |
| `ios` | No | Sí (GVS o Player), incluso en HLS |
| `tv` | No requiere runtime propio | No requerido (pero formatos con DRM si no hay cookies) |

Nota de importante: **El enforcement de YouTube es cambiante e intermitente**, y la documentación de los clientes antes expuestos en la tabla puede quedar desactualizada respecto al comportamiento real observado en producción de un día a otro. Actualmente no existe hoy una combinación "gratuita" garantizada, todo cliente que evita el runtime de JS tiende a exigir PO Token, y todo cliente que evita el PO Token tiende a exigir runtime de JS.

## 5. Glosario de términos técnicos usados en la tabla de clientes

La tabla de la sección anterior usó varios términos técnicos (HTTPS, DASH, HLS, GVS, Player, Subs, DRM, SABR) que conviene definir para entenderla en su totalidad.

### 5.1. HTTPS / DASH / HLS: Los tres "protocolos de streaming"

Son las tres formas en que YouTube puede entregar el audio/video:

- **HTTPS**: un único archivo de audio/video servido como stream adaptativo directo (una sola URL descargable de principio a fin).
- **DASH** (Dynamic Adaptive Streaming over HTTP): el contenido se divide en un "manifiesto" que describe múltiples fragmentos/calidades, permitiendo cambiar de calidad sobre la marcha.
- **HLS** (HTTP Live Streaming): protocolo de streaming creado por Apple, basado en listas de reproducción `.m3u8` con segmentos `.ts`.

Cada uno de estos tres protocolos tiene su **propia política de PO Token independiente** por cliente. En la práctica, YouTube ha sido consistentemente más permisivo con HLS: casi todos los clientes NO exigen PO Token para HLS, mientras que HTTPS y DASH casi siempre sí lo exigen.

### 5.2. GVS (Google Video Server)

Es el nombre del servidor/infraestructura de Google que finalmente entrega el archivo de audio/video en sí (las URLs `googlevideo.com`). Es uno de los tres "contextos" en los que YouTube puede exigir un PO Token.

### 5.3. Player (Player PO Token)

Es un contexto distinto al de GVS: se refiere a la petición inicial a la API interna de YouTube (Innertube) que devuelve el JSON con la lista de formatos disponibles para el video, antes incluso de descargar nada. Algunos clientes (`android`, `ios`) exigen PO Token en esta etapa, lo que significa que ni siquiera pueden completar el primer paso de "preguntar qué formatos hay" sin el token.

### 5.4. Subs (Subtítulos)

Es el tercer contexto de PO Token: se refiere a peticiones de subtítulos, que pueden requerir su propio token independiente del de audio/video. No afecta directamente a un bot de música salvo que también se quieran subtítulos.

### 5.5. DRM (Digital Rights Management)

Mecanismo de protección de contenido completamente distinto al PO Token — no es anti-bot, es anti-copia. Algunos videos (por licencias musicales, contenido protegido) traen formatos marcados como protegidos por DRM, y yt-dlp los descarta directamente porque no puede desencriptarlos. Si todos los formatos de un video tienen DRM, yt-dlp lanza un error explícito de "DRM protected". Es importante no confundir un fallo de DRM con un fallo de PO Token faltante: son dos causas distintas de que un formato no esté disponible.

### 5.6. SABR (Server-Adaptive Bitrate)

Es el mecanismo de streaming más nuevo que YouTube está empujando activamente, pensado para reemplazar las URLs directas descargables por un protocolo propietario donde el servidor decide dinámicamente qué calidad enviar. Cuando YouTube fuerza SABR para un cliente, simplemente no entrega una URL de descarga normal. yt-dlp es incapaz de trabajar con ellos y directamente descarta esos formatos.

## 6. Alternativas reales disponibles hoy, y sus contrapartidas

La recomendación oficial actual de yt-dlp, citada textualmente de su wiki, es:

> "At this time, if you are having issues with the default clients, it is suggested to use the `mweb` client with a PO Token."

1. **Usar un PO Token Provider plugin (recomendado por el propio proyecto)**: Por ejemplo `bgutil-ytdlp-pot-provider`, que automatiza la generación de PO Tokens para el cliente `mweb`. Contrapartida: agrega una dependencia externa adicional (y potencialmente otro proceso/servicio corriendo en segundo plano) al bot, lo cual complica el objetivo de distribución como `.exe` portable de este proyecto.
2. **Proveer manualmente un PO Token vía `--extractor-args`** : Técnicamente posible, pero los tokens están ligados al ID de cada video y expiran, por lo que no es una solución "configúralo una vez y olvídate"; requeriría automatizar su generación (lo cual es, en esencia, reinventar un PO Token Provider).
3. **Instalar un runtime de JS (Deno) + `yt-dlp-ejs`** para habilitar el cliente `web`: Resuelve el problema de la firma/n-challenge, pero **no resuelve el PO Token** que `web` también exige para GVS; solo evita el fallo de "formato no disponible", no necesariamente el 403.

## 7. Conclusión

El bot de música no falla por un error de configuración simple ni por un bug puntual: Sino por reflejo de un **endurecimiento deliberado y activo por parte de YouTube contra la extracción automatizada de videos** que yt-dlp documenta abiertamente como un problema en curso y sin solución "de fábrica" definitiva. Cualquier solución que se adopte (plugin de PO Token, runtime de JS) debe entenderse como una **mitigación con contrapartidas**, no como una corrección permanente, y el propio proyecto advierte que el comportamiento de YouTube cambia de forma "intermitente" y que la documentación puede no reflejar el estado exacto en todo momento.

## 8. Decisión de arquitectura para vPetal: Priorizar clientes que solo dependan de JS Runtime

Tras comparar los dos mecanismos anti-bot en profundidad, se optó por una estrategia deliberada: **priorizar el uso de clientes que solo requieran JS Runtime (sin PO Token), evitando en la medida de lo posible cualquier cliente que dependa de un PO Token Provider externo.**

### 8.1. Por qué el JS Runtime es la opción "más robusta" a largo plazo

- **Está mantenido por el propio equipo core de yt-dlp**, como parte del proyecto hermano oficial `yt-dlp/ejs`. No depende de terceros no afiliados al proyecto.
- **El mecanismo no "adivina" el algoritmo de YouTube**: yt-dlp descarga y ejecuta el script real de resolución (`yt.solver.lib.js` / `yt.solver.core.js`) en un motor de JS de verdad (Deno, Node, Bun o QuickJS), verificando su hash antes de correrlo. Es un enfoque determinístico, no una réplica manual en Python que se rompe con cada cambio de YouTube.
- **Historial de mantenimiento predecible**: Cuando YouTube cambia su reproductor y rompe la extracción de firma/n-challenge, el equipo de yt-dlp lo corrige como parte de su ciclo normal de releases, con precedentes documentados en el `Changelog.md` de su github donde en varios puntos de los últimos 2 años el patrón es consistente: YouTube cambia su reproductor JS, el algoritmo de extracción de yt-dlp se rompe, y el equipo de yt-dlp lo arregla en días o a veces en cuestión de horas. Es un problema recurrente pero gestionado activamente y de forma predecible por el mismo proyecto.

**Contra de esta opción:** Sigue siendo necesario instalar y distribuir un runtime de JS junto al bot, lo cual añade una dependencia binaria adicional al plan de empaquetado con PyInstaller. Además, no elimina el riesgo de que, en el futuro, YouTube empiece a exigir también PO Token a los todos los clientes sin excepción incluyendo a los que hoy en día no lo requieren.

### 8.2. Por qué el PO Token es la opción "menos predecible" a largo plazo

- **yt-dlp no implementa ningún generador de PO Token en su propio core**: El sistema interno (`PoTokenRequestDirector`) es solo un *framework* que orquesta proveedores, pero no trae ninguno integrado, sino que depende enteramente de que un plugin externo (`bgutil-ytdlp-pot-provider`, `yt-dlp-getpot-wpc`, etc.) lo resuelva.
- **El problema que resuelve el PO Token es de naturaleza adversarial** (attestation criptográfica tipo BotGuard/DroidGuard/iOSGuard), mucho más difícil de replicar de forma sostenida que "ejecutar JavaScript", y más parecido en espíritu a burlar un sistema DRM.
- **Tendencia observada de endurecimiento activo**: La propia configuración de clientes como `android_vr` documenta en comentarios que YouTube ha ido intensificando el enforcement de PO Token de forma creciente y selectiva, con casos confirmados donde un cliente que antes funcionaba sin problema pasó a devolver error 403 en todos sus formatos de un día para otro.
- **Dependencia de infraestructura adicional**: La mayoría de los PO Token Provider plugins recomendados corren como un proceso/servicio separado (no solo una librería importada), lo cual complica significativamente el objetivo de vPetal de distribuirse como un `.exe` portable sin instalaciones previas por parte del usuario final.

### 8.3. Enfoque adoptado por el proyecto

vPetal intentará configurar `yt-dlp` para restringirse a clientes cuya única dependencia sea un runtime de JS instalado localmente, **evitando activamente cualquier cliente cuya política declare requerimiento de PO Token** (`GVS_PO_TOKEN_POLICY.required = True`). Esto implica, en la práctica, priorizar formatos servidos vía protocolos donde el PO Token no sea exigido (HLS, principalmente) sobre formatos DASH/HTTPS directos que sí lo exigen en casi todos los clientes disponibles.

Esta decisión no garantiza inmunidad total a futuros cambios de YouTube, pero reduce la superficie de dependencia externa del proyecto a un único componente mantenido oficialmente (`yt-dlp-ejs`), en vez de sumar además una dependencia de un plugin de terceros no afiliado al proyecto `yt-dlp`.