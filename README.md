# Buscacoches

Borrador de una web para quien busca coche. Eliges marca, modelo, motorización y cambio, y la página muestra:

- **Precio de nuevo** de cada motorización (tarifa y precio con descuentos).
- **Pérdida de valor** estimada para cada modelo y motorización, a partir del valor que conserva un coche a los 3 años según su tipo de motor (Ganvam) y la tabla de depreciación de Hacienda, junto a los coches reales cuando los hay.
- **Ocasión oficial de la marca**: distribución de precios por tramos de 10.000 km (diagrama de cajas) y enlace a la web oficial.
- **Portales de segunda mano**: el mismo diagrama con los anuncios de Coches.net, Motor.es, Coches.com y Flexicar juntos, sin repetidos.
- **Seguro estimado** (terceros, terceros ampliado y todo riesgo) según la edad del conductor, los kilómetros al año, la potencia y el precio del coche. Es orientativo: la página explica qué parte son datos y qué parte supuestos.
- **Enlaces** a las webs de segunda mano con la búsqueda hecha.

La web es un único archivo, `index.html`. Al abrirla desde GitHub Pages (o cualquier servidor) carga además los precios de ocasión de `datos/ocasion/`, que se actualizan cada noche.

## Datos fijos

Recogidos a mano en octubre de 2026 (70 marcas):

- `datos/catalogo.json`: marcas, modelos y motorizaciones que usa el lector.
- `datos/motores.txt` y `datos/precios.txt`: motorizaciones y precio de nuevo por motorización (fichas de Motor.es).
- Seguro: Índice Kelisto, Check24 y Rastreator. Depreciación: Ganvam y tabla de Hacienda.

## Análisis nocturno de precios de ocasión

Cada noche, GitHub Actions (`.github/workflows/nocturno.yml`) ejecuta `scraper/lector.py`, que:

1. Recorre los modelos de `datos/catalogo.json`.
2. Lee los anuncios de los portales (Motor.es, Coches.com, Coches.net y Flexicar) y de las webs oficiales que se dejan leer (BMW Premium Selection, Renew para Renault y Dacia, y Spoticar para Peugeot, Citroën, Opel, Fiat, Jeep, Alfa Romeo, DS, Lancia y Abarth).
3. Asigna cada anuncio a una motorización por potencia, combustible y cilindrada, y quita los coches repetidos entre webs.
4. Guarda un archivo por modelo en `datos/ocasion/` y un resumen de cada web en `datos/informe.json`.

La web carga esos archivos al elegir un modelo. El lector respeta el robots.txt de cada web, espera entre peticiones y deja de leer una web si lo bloquea.

- **Ejecutarlo a mano:** pestaña Actions → «Análisis nocturno de precios de ocasión» → Run workflow (modo `completo` o `prueba`).
- **Lanzarlo al momento:** cualquier cambio en el lector, o en el archivo `.github/lanzar`, ejecuta el análisis completo.
- **Modo prueba** (desde Run workflow): lee 4 modelos y guarda muestras de las páginas en `debug/` para revisar la extracción.
- **En local:** `pip install -r scraper/requirements.txt` y `python scraper/lector.py --modelos "Kia|Ceed"`.

> Aviso: los anuncios pertenecen a cada portal. Este análisis es para uso personal.

## Pendiente

- Comprobar en la primera ejecución qué webs devuelven anuncios y ajustar la lectura de las que no (el resumen de cada trabajo en Actions lo indica).
- Motorizaciones de los modelos que ya no se fabrican.
- Precios de seguro reales mediante acuerdo con un comparador.
