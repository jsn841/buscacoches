# Buscacoches

Borrador de una web para quien busca coche. Eliges marca, modelo, motorización y cambio, y la página muestra:

- **Precio de nuevo** de cada motorización (tarifa y precio con descuentos).
- **Pérdida de valor** con los kilómetros y los años, a partir de coches reales de las webs oficiales de ocasión de las marcas (por ahora, BMW Serie 3 y Renault Captur).
- **Ocasión oficial de la marca**: precio medio por tramos de kilómetros y enlace a la web oficial.
- **Seguro estimado** (terceros, terceros ampliado y todo riesgo) según la edad del conductor, los kilómetros al año, la potencia y el precio del coche. Es una estimación orientativa: la página explica qué parte son datos y qué parte son supuestos.
- **Segunda mano**: enlaces directos a AutoScout24, Wallapop, Coches.net, Milanuncios y otras webs.

Todo está en un único archivo, `index.html`, sin dependencias. Se puede abrir directamente en el navegador o publicar con GitHub Pages.

## Datos

Recogidos a mano el 18 de octubre de 2026:

- `datos/motores.txt`: motorizaciones por modelo (nombre, CV, combustible y cambio).
- `datos/precios.txt`: precio de tarifa y con descuentos por motorización.
- Fuentes: fichas de modelos de Motor.es, BMW Premium Selection, Renew (Renault), Índice Kelisto de seguros, Check24 y Rastreator.

## Pendiente

- Lector automático de las webs oficiales de ocasión (BMW Premium Selection y Renew) para tener medias de todos los modelos y que se actualicen solas.
- Motorizaciones de los modelos que ya no se fabrican.
- Precios de seguro reales mediante acuerdo con un comparador.
