# Panel de administración de casino

Demo educativa y local de un panel de administración para un casino en línea y una experiencia de
juego separada para jugadores. Utiliza datos ficticios y créditos de demostración; no es un servicio
de apuestas con dinero real.

**Tecnologías:** FastAPI, SQLAlchemy y PostgreSQL (API/base de datos); React, TypeScript y Vite
(aplicación web).

## Ejecutar localmente con Docker

La forma recomendada de ejecutar el proyecto es con Docker Compose, que inicia PostgreSQL, la API y
el servidor de desarrollo de Vite. No necesitas instalar Python ni PostgreSQL en tu computadora.

### Requisitos previos

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) o Docker Engine
  con el complemento de Docker Compose (Linux)
- Un navegador moderno

Inicia Docker Desktop (o el servicio Docker Engine), clona el repositorio y entra en su carpeta:

```bash
git clone https://github.com/andrestylev/Dashboard_Casino.git
cd Dashboard_Casino
```

Construye e inicia los servicios:

```bash
docker compose up --build -d
```

En el primer inicio, PostgreSQL crea la base de datos `casino`, carga el conjunto de datos ficticios
y configura el esquema incluido. Actualiza el esquema a la última revisión (este comando funciona
tanto con una base nueva como con una existente):

```bash
docker compose run --rm api alembic upgrade head
```

Abre la aplicación:

| Página | URL |
| --- | --- |
| Panel de administración | <http://localhost:5173/login> |
| Demo del casino para jugadores | <http://localhost:5173/casino> |
| Documentación de la API | <http://localhost:8000/api/docs> |
| Comprobación de estado de la API | <http://localhost:8000/api/health> |

Inicia sesión con la cuenta de administrador incluida en los datos de demostración:

```text
Usuario: andres.molina
Contraseña: Demo-Casino-2026!
```

La demo para jugadores está separada: crea una cuenta para mayores de edad en `/casino/register`.
Cada cuenta comienza con 1.000 créditos ficticios. No hay depósitos, retiros, compras ni premios
canjeables.

### Detener, reiniciar y restablecer

Detén los contenedores sin borrar la base de datos ni los datos de los jugadores:

```bash
docker compose down
```

Inicia de nuevo los servicios existentes:

```bash
docker compose up -d
```

Para borrar definitivamente la base de datos local y empezar de nuevo con los datos de demostración:

```bash
docker compose down -v
docker compose up --build -d
docker compose run --rm api alembic upgrade head
```

> **Advertencia:** `docker compose down -v` elimina el volumen de datos de PostgreSQL, incluidas las
> cuentas de jugador creadas durante el uso de la demo. No lo ejecutes si quieres conservar tus datos.

### Comandos útiles de Docker

```bash
docker compose ps                 # Ver los servicios en ejecución
docker compose logs -f api        # Seguir los registros de la API; Ctrl+C deja de seguirlos
docker compose logs -f db         # Seguir los registros de PostgreSQL
docker compose run --rm api alembic current
```

Los puertos predeterminados son `5173` (Vite), `8000` (API) y `55432` (PostgreSQL). Si alguno ya está
en uso, detén la aplicación que lo utiliza o cambia el puerto correspondiente del equipo anfitrión
en `docker-compose.yml` antes de iniciar los servicios. Las credenciales de PostgreSQL de Compose
son solo para desarrollo local; no expongas esta configuración a Internet.

## Estructura del proyecto

```text
api/                 Aplicación FastAPI, modelos SQLAlchemy, migraciones y pruebas
web/                 Interfaz React + TypeScript y pruebas de navegador
seed/                Datos ficticios de PostgreSQL y configuración del esquema portable
docs/                Diagrama de la base de datos y documentación del proyecto
packaging/windows/   Scripts del paquete de demostración portable para Windows
docker-compose.yml   Entorno local de desarrollo con PostgreSQL, API y Vite
```

El panel de administración incluye autenticación, análisis, tablas de jugadores/juegos/transacciones,
gestión de riesgos e historial de auditoría. La demo para jugadores incluye registro, créditos
ficticios, tragamonedas y blackjack. Consulta el [diagrama de la base de datos](docs/erd.md) y la
[guía del paquete portable para Windows](packaging/windows/README.md).

## Desarrollo

La configuración de Compose monta las carpetas de código fuente dentro de los contenedores. Los
cambios en `web/src/` se reflejan en <http://localhost:5173> mediante la recarga en caliente de Vite.
Uvicorn detecta y aplica automáticamente los cambios en `api/app/`.

Para ejecutar el frontend directamente en tu computadora en vez de hacerlo en Docker, instala
Node.js 22 o posterior y ejecuta:

```bash
cd web
npm ci
npm run dev
```

Por defecto, Vite redirige las solicitudes a `/api` hacia `http://localhost:8000`, por lo que la API
y PostgreSQL deben seguir en ejecución. Para compilar el frontend estático que sirve FastAPI,
ejecuta `npm run build` desde `web/`; el resultado se guarda en `web/dist/`. El frontend usa las
fuentes del sistema y no necesita conexión a Internet una vez instaladas las dependencias.

### Ejecutar las pruebas

Primero inicia los servicios de Docker. Desde la carpeta raíz del repositorio, ejecuta las pruebas
de la API y del esquema:

```bash
docker compose run --rm api python -m pytest -q tests
```

Las pruebas de la API recrean la base de datos exclusiva `casino_test`, configurada en Docker
Compose. Nunca configures `TEST_DATABASE_URL` con una base de datos que contenga información que
quieras conservar. Para ejecutar las pruebas de navegador, instala Node.js 22 o posterior y sigue
los comandos de frontend en [Fase 7](#fase-7-rendimiento-accesibilidad-y-diseño-adaptable).

El ZIP portable para Windows sirve este frontend compilado desde FastAPI; no inicia Vite, por lo que
no recarga automáticamente los cambios hechos después de crear el ZIP. El script
`packaging/windows/build_bundle.ps1` compila el frontend antes de crear cada ZIP. Después de editar
la interfaz, ejecuta el script y copia o extrae el nuevo `dist/casino-demo.zip` en la computadora
donde harás la presentación. Node.js y npm solo se necesitan en la computadora donde se construye
el paquete, no en la computadora de presentación. Para ver los cambios de interfaz al instante
durante el desarrollo, usa `docker compose up --build` y abre `http://localhost:5173`.

### Demo del casino para jugadores

La experiencia para jugadores está en <http://localhost:5173/casino> (inicia sesión en
<http://localhost:5173/casino/login> o regístrate en
<http://localhost:5173/casino/register>). Utiliza su propia cookie `player_session` y rutas de API
bajo `/api/player`. No usa las cuentas de administrador, la billetera de dinero existente ni los
registros de transacciones. El registro es solo para personas adultas; la API valida la fecha de
nacimiento y asigna 1.000 créditos ficticios a cada cuenta nueva. Una vez al día, según UTC, el saldo
se recarga hasta un máximo de 1.000 créditos. Cada movimiento queda registrado en el ledger
independiente `demo_credit_entries`.

La demo ofrece Lucky Lanterns y blackjack clásico. Las apuestas van de 10 a 100 créditos, en
incrementos de 10. Tres símbolos iguales en la tragamonedas pagan 2×, 3×, 5× o 10×, según el
símbolo. En blackjack, un natural paga 3:2, una victoria normal paga 2:1 y un empate devuelve la
apuesta. Se permite dividir una vez cuando las dos primeras cartas tienen el mismo valor; al
dividir ases, cada mano recibe una carta y se planta automáticamente. El crupier pide cartas hasta
igualar o superar la mano válida más alta. La API calcula todo el estado y los resultados de la
partida. El saldo no puede superar 1.000 créditos, que no se pueden comprar, retirar ni canjear por
premios o dinero.

### Fase 4: frontend

Los administradores inician sesión con un nombre de usuario y una contraseña. Para solicitar una
cuenta nueva se necesita un nombre de usuario, nombre completo, correo electrónico y una contraseña
de al menos 12 caracteres. Cada solicitud recibe el rol de mínimo privilegio `support` y permanece
inactiva hasta que un `super_admin` la apruebe en **Solicitudes de acceso**. El registro no envía ni
verifica correos electrónicos. En las cuentas de los datos de demostración se usa como nombre de
usuario la parte del correo anterior a `@` (por ejemplo, `camila.restrepo`).

La navegación protegida incluye Panel, Jugadores, Juegos, Transacciones, Apuestas y Alertas de
riesgo. Los `super_admin` también pueden ver Solicitudes de acceso y el Registro de auditoría; las
rutas del frontend y la API restringen estas páginas según el rol. Las tablas usan paginación en el
servidor, con 10 filas por página. Jugadores y Juegos también permiten búsquedas en la API. Las
funciones de gestión se describen en la Fase 6. FastAPI sirve la aplicación compilada y redirige
las rutas del frontend a su página de inicio, por lo que también funcionan los enlaces directos y
la recarga de páginas.

### Fase 5: métricas del panel

Después de iniciar sesión, el Panel protegido es la página predeterminada. Muestra inicialmente los
últimos 30 días según UTC y ofrece un rango de fechas común para las tarjetas y los gráficos
diarios. Las métricas se actualizan automáticamente cada cinco segundos mientras el panel está
abierto, y de inmediato cuando se cambian las fechas o el período del canal de registro.

- **GGR (ingresos brutos del juego):** suma de las apuestas menos los premios pagados, agrupada
  por fecha de apuesta.
- **Depósitos y retiros completados:** suma de las transacciones con estado `completed`, agrupada
  por fecha de finalización. Se excluyen las transacciones pendientes y fallidas.
- **Jugadores activos:** cantidad de jugadores distintos que hicieron una o más apuestas en el
  período seleccionado.
- **Apuestas realizadas:** cantidad de apuestas efectuadas durante el período seleccionado.
- Los gráficos diarios muestran el GGR y los depósitos/retiros completados. Los días sin actividad
  muestran cero.
- Una tarjeta muestra el GGR de todos los tiempos: la suma de las apuestas menos los premios
  pagados. El gráfico de GGR de seis meses muestra una barra por cada mes calendario según UTC,
  incluido el mes actual, aunque todavía esté en curso.
- Las estadísticas de jugadores muestran la distribución del **canal de registro** Web/Mobile
  (todos los tiempos de forma predeterminada, con filtros del último mes, 3 meses o 6 meses), la
  distribución de niveles VIP de todos los tiempos y los rangos de edad actuales (18–25, 26–35,
  36–45, 46–55 y 56+), con cantidades y porcentajes. La edad se calcula a partir de la fecha de
  nacimiento y la fecha actual según UTC.
- El mapa de actividad de apuestas de todos los tiempos agrupa las cantidades por día de la semana
  y hora según UTC.

La base de datos registra el canal de registro del jugador, no el dispositivo que utiliza en cada
inicio de sesión. Por tanto, el gráfico circular Web/Mobile representa el origen del registro y no
la actividad real de inicio de sesión o conexión.

La ruta de la API de métricas es
`GET /api/dashboard/metrics?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&registration_months=all`,
en la que `registration_months` acepta `all`, `1`, `3` o `6`.
Los límites de fecha usan UTC y se incluyen ambas fechas seleccionadas. Si el rango supera los 366
días o la fecha final es anterior a la inicial, la API responde `422`. La ruta requiere una sesión
de administrador autenticada y calcula los agregados en PostgreSQL, sin cargar en memoria las
tablas completas de transacciones o apuestas.

### Idioma y apariencia

La interfaz del panel está disponible en inglés y español. La primera vez, utiliza el idioma del
navegador (español si la configuración regional del navegador es español; inglés en caso
contrario). Puedes elegir el idioma con el selector de banderas de la pantalla de inicio de sesión
o de la barra superior; la preferencia se guarda en el navegador. Los datos del usuario y de la
base de datos, como nombres, nombres de usuario y juegos, no se traducen.

Inicialmente, el tema de color sigue la preferencia clara u oscura del sistema operativo y se
actualiza cuando esta cambia. Usa el botón de tema en la pantalla de inicio de sesión o en la barra
superior para cambiar manualmente entre el tema claro y el oscuro. La selección manual se guarda
en este navegador y prevalece sobre la configuración del sistema.

### Fase 6: gestión y riesgos

Las tablas de gestión permiten combinar filtros procesados en el servidor, abrir paneles con el
detalle de cada registro y descargar en CSV todas las filas que coincidan con los filtros
aplicados, no solo las de la página visible. Las exportaciones CSV tienen un límite de 10.000
filas; si se supera, la API responde `413`, así que añade más filtros e inténtalo de nuevo. Las
exportaciones se registran en la auditoría, las celdas de texto CSV están protegidas contra la
inyección de fórmulas en hojas de cálculo y las descargas se marcan como `no-store`.

- **Jugadores:** filtra por estado, KYC, nivel VIP, país o fechas de registro y consulta el perfil
  completo. Solo `super_admin` puede cambiar el estado o cerrar una cuenta. Las cuentas cerradas no
  pueden reactivarse y no se puede anular una autoexclusión activa.
- **Juegos:** filtra por categoría, proveedor y disponibilidad, y consulta los detalles del
  catálogo. Solo `super_admin` puede activar o desactivar juegos. Esto no modifica las apuestas
  históricas.
- **Alertas de riesgo:** filtra por jugador, señal, gravedad, estado o fechas de creación. Ambos
  roles pueden asignarse una alerta abierta para revisarla y luego resolverla o descartarla con una
  nota obligatoria. Las alertas resueltas o descartadas no se pueden reabrir.
- **Transacciones y apuestas:** permiten consultar detalles y aplicar filtros, pero no se pueden
  modificar desde este panel. En esta fase no hay ajustes de saldo ni operaciones financieras de
  escritura.
- Todas las modificaciones de gestión se guardan en `audit_log`. La API también aplica los
  permisos, además de los controles de interfaz según el rol.

### Fase 7: rendimiento, accesibilidad y diseño adaptable

Las principales consultas de agregación y listado del panel se revisaron con `EXPLAIN ANALYZE` de
PostgreSQL y la base de datos de demostración. Las consultas selectivas por rango de fechas usan
los índices existentes para fechas y registros. En esta muestra local, la agregación de apuestas
de 30 días tardó aproximadamente 20 ms, el GGR diario unos 10 ms, el GGR de todos los tiempos unos
19 ms y el mapa de actividad completo unos 42 ms. Son mediciones de desarrollo, no pruebas de
rendimiento en producción. No se añadieron índices porque los planes y tiempos observados no
justificaron el costo adicional de escritura y almacenamiento.

El frontend incluye etiquetas y regiones semánticas, foco visible al usar el teclado, compatibilidad
con la opción de movimiento reducido y un menú de navegación adaptable que se puede operar con el
teclado. Las pruebas E2E de Playwright verifican la persistencia de preferencias, el inicio de
sesión y la navegación del panel, el desbordamiento y la navegación en móviles, y las reglas
automatizadas WCAG 2/2.1 A/AA en el inicio de sesión, el panel (temas claro y oscuro) y la tabla de
jugadores en móvil.

Para ejecutar las comprobaciones del frontend desde la carpeta raíz del repositorio:

```
cd web
npm ci
npm exec playwright install chromium
npm run build
npm run test:e2e
```

Las pruebas E2E simulan las respuestas de la API y ejecutan Vite localmente, por lo que no requieren
los contenedores de la API ni de la base de datos. La integración continua instala Chromium,
compila el frontend y ejecuta la misma suite de pruebas.

Rutas de gestión añadidas:

| Ruta | Función |
| --- | --- |
| `GET /api/games/{id}/detail`, `GET /api/transactions/{id}/detail` | Consultar los detalles de un juego o una transacción. |
| `GET /api/bets/{id}/detail`, `GET /api/risk-alerts/{id}/detail` | Consultar los detalles de una apuesta o una alerta de riesgo. |
| `PATCH /api/players/{id}/status` | Cambiar el estado de un jugador; solo `super_admin`. |
| `PATCH /api/games/{id}/status` | Cambiar la disponibilidad de un juego; solo `super_admin`. |
| `PATCH /api/risk-alerts/{id}` | Asignar para revisión, resolver o descartar con una nota; ambos roles de administración. |
| `GET /api/exports/{resource}.csv` | Exportar jugadores, juegos, transacciones, apuestas o alertas filtrados (máximo 10.000 filas). |

## Fase 3: API y autenticación

La documentación de la API está en `http://localhost:8000/api/docs`. Salvo que se indique lo
contrario, las rutas siguientes requieren una sesión autenticada de administrador:

| Ruta | Función |
| --- | --- |
| `POST /api/auth/login` | Verificar el nombre de usuario y la contraseña de un administrador. |
| `POST /api/auth/register` | Solicitar una cuenta de soporte con nombre de usuario, nombre completo, correo y contraseña; se debe aprobar antes de iniciar sesión. |
| `POST /api/auth/refresh` | Rotar el token de sesión y extender su vigencia de 12 horas. |
| `POST /api/auth/logout` | Revocar la sesión actual y borrar su cookie. |
| `GET /api/auth/me` | Devolver el administrador que inició sesión y su rol. |
| `GET /api/dashboard/metrics` | Devolver indicadores y tendencias diarias filtrados por fecha para el administrador autenticado. |
| `GET /api/admin/pending-registrations` | Listar solicitudes de cuenta; solo `super_admin`. |
| `POST /api/admin/users/{id}/approve` | Aprobar una solicitud con el rol `support`; solo `super_admin`. |
| `GET /api/players`, `GET /api/players/{id}` | Buscar y consultar jugadores, incluido el saldo de su billetera. |
| `PATCH /api/players/{id}/status` | Cambiar el estado de un jugador; solo `super_admin`. |
| `GET /api/games` | Filtrar juegos por categoría, proveedor, estado activo o nombre. |
| `PATCH /api/games/{id}/status` | Cambiar la disponibilidad de un juego; solo `super_admin`. |
| `GET /api/transactions` | Filtrar transacciones por jugador, tipo, estado o rango de fechas. |
| `GET /api/bets` | Filtrar apuestas por jugador, juego, resultado o rango de fechas. |
| `GET /api/risk-alerts`, `PATCH /api/risk-alerts/{id}` | Filtrar alertas y avanzar su revisión o resolución. |
| `GET /api/exports/{resource}.csv` | Exportar hasta 10.000 filas que coincidan con los filtros; registra un evento de auditoría. |
| `GET /api/audit-log` | Buscar en el registro de auditoría; solo `super_admin`. |

Las rutas de listado devuelven `{items, total, page, page_size}` y aceptan `page` y `page_size`
(máximo 100). Cinco intentos fallidos de inicio de sesión bloquean la cuenta durante 15 minutos. Los
eventos de inicio de sesión, sesión, registro y fallos de autenticación se guardan en el registro de
auditoría.

El token de sesión es opaco, se almacena como hash en PostgreSQL y se envía en una cookie
`HttpOnly`, `SameSite=Strict`, limitada a `/api`. Para usar HTTPS, configura
`SECURE_AUTH_COOKIES=true`. Esta demo utiliza autenticación solo con contraseña; úsala únicamente en
un entorno local de presentación y no la expongas directamente a Internet.

La base de demostración se inicializa desde `seed/casino_demo.sql` la primera vez que PostgreSQL
crea su volumen de datos. Para generar o actualizar el volcado sin reemplazar la base de datos de
desarrollo, crea una base de exportación independiente:

```
docker compose up --build -d db
docker compose exec -T db createdb -U postgres casino_seed_export
docker compose run --rm -e DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/casino_seed_export api alembic upgrade head
docker compose run --rm -e DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/casino_seed_export api python -m scripts.seed --database-url postgresql+psycopg://postgres:postgres@db:5432/casino_seed_export --seed 42 --as-of 2026-10-23
docker compose exec -T db pg_dump -U postgres -d casino_seed_export --no-owner --no-privileges > seed/casino_demo.sql
```

El inicializador de la base de datos también ejecuta `seed/zzz_admin_usernames.sql`, que agrega la
columna de nombre de usuario a los volcados antiguos. Si una base de desarrollo existente se
inicializó con un volcado antiguo y no tiene una revisión de Alembic, ejecuta una sola vez
`docker compose run --rm api alembic stamp 0001` y después
`docker compose run --rm api alembic upgrade head`. Primero comprueba `alembic current`; no marques
una base que ya tenga una revisión. Genera los próximos volcados de datos solo desde una base
migrada a `head`.

El conjunto de datos predeterminado contiene 1.200 jugadores ficticios y 180 días de actividad.
Usa una fecha fija con `--as-of` y el mismo valor de `--seed` para reproducir los mismos registros.
La opción `--reset` reemplaza los datos de la base configurada; úsala solo con la base de
exportación desechable. Para actualizar los datos posteriormente, omite los comandos `createdb` y
de migración, y añade `--reset` al comando del generador. Antes de guardar, el generador valida los
libros contables de las billeteras, los saldos, las fechas y las alertas de riesgo insertadas.

En PowerShell, usa una versión moderna que redirija la salida de comandos nativos con codificación
UTF-8 o ejecuta el comando mediante `cmd /c` para conservar la codificación del archivo SQL. Vuelve
a generar el paquete de Windows después de actualizar el volcado. Las cuentas de administrador de
demostración usan la contraseña indicada por el generador; las credenciales y los registros son
ficticios y se deben usar únicamente en presentaciones locales.

Para cambiar el esquema, edita los modelos en `api/app/models/` y luego ejecuta:

```
docker compose run --rm api alembic revision --autogenerate -m "describe el cambio"
# Revisa el archivo generado en api/alembic/versions/ y luego ejecuta:
docker compose run --rm api alembic upgrade head
python api/scripts/generate_erd.py              # actualiza docs/erd.md
```

La prueba `test_models_match_migrations` falla si se modifica un modelo sin crear su migración.

Sin Docker:

```
python -m venv .venv && .venv\Scripts\activate       # Windows
pip install -r api/requirements-dev.txt
ruff check .
pytest                      # Las pruebas de esquema y datos necesitan PostgreSQL; configura TEST_DATABASE_URL (ver .env.example)
```

## Presentar el proyecto en otra computadora

Consulta la [guía del paquete portable para Windows](packaging/windows/README.md) para compilarlo y
ejecutarlo. La cuenta de presentación `andres.molina` usa la contraseña predeterminada
`Demo-Casino-2026!`; tanto las credenciales como los datos son ficticios. El paquete incluye sus
propios ejecutables de Python y PostgreSQL, y selecciona puertos locales disponibles. No es
necesario cambiar ni detener las versiones instaladas en la computadora, y no se requieren
permisos de administrador.
