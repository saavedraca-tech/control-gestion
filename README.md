# Control de gestión mensual · ARFinance

Sistema para armar, todos los meses y para cada cliente PyME, un **tablero en Excel** con los
indicadores (KPIs) en semáforo, el **resultado operativo**, gráficos, clientes, compras, personal y
alertas, más un **resumen de una página** para la reunión con los socios.

Se usa con **un solo comando** y no hace falta saber programar. Todo lo propio de cada cliente
(reglas de proveedores, metas, alícuotas, personal) está en archivos de texto `.yaml` que se editan
con el Bloc de notas.

---

## Qué hacer cada mes (5 pasos)

1. **Crear la carpeta del mes** dentro de `clientes/<cliente>/entrada/`, con el nombre `AAAA-MM`
   (por ejemplo `2026-11`).
2. **Dejar ahí los archivos del mes**:
   - el CSV de comprobantes **emitidos** de ARCA;
   - el CSV de comprobantes **recibidos** de ARCA;
   - el **PDF del F.931**;
   - el **PDF del extracto bancario**;
   - si los hay, los opcionales (ver la tabla de abajo).
3. **Correr el cierre**. Abrir la terminal en la carpeta `control-gestion` y escribir:
   ```
   python cierre.py --cliente duclos --mes 2026-11
   ```
   Para cerrar todos los clientes juntos: `python cierre.py --todos --mes 2026-11`.
   (Sin escribir comandos: doble clic en **`Cierre_mensual.bat`**, que pregunta el cliente y el mes.)

   Lo que se ve en la terminal (cierre real de Duclos, octubre 2026):
   ```
   === DUCLOS SAS · cierre de octubre 2026 ===
     Archivos leídos: 0 nuevos o modificados, 19 ya procesados
     Ventas: $ 2.542.440 · Resultado operativo: -$ 1.262.219
       ▫️ Ventas netas facturadas: $ 2.542.440
       ⚪ Precio promedio por bolsa: sin dato
       🔴 Resultado operativo: -$ 1.262.219
       ⚪ Caja en días de gastos fijos: sin dato
       ⚪ Días de cobertura de stock: sin dato
       🔴 Energía / ventas: 110,5 %
       ⚪ kWh por bolsa: sin dato
       ⚪ Reparto / ventas: sin dato
     Alertas: 6 alta(s), 36 media(s)
     Archivos generados en ...\clientes\duclos\salida\2026-10
   ```
4. **Revisar la hoja *Alertas*** del Excel que se generó en `clientes/<cliente>/salida/2026-11/`. Si
   aparece un proveedor sin regla, agregarle la regla en `rubros.yaml` y repetir el paso 3.
5. **Mandar a los socios** el `Resumen_reunion_2026-11.pdf`. Después de la reunión, anotar lo que se
   decidió en la hoja *Decisiones* del Excel; esa hoja pasa sola al mes siguiente.

> Se puede correr el cierre todas las veces que haga falta: **no duplica nada**. Si un archivo se
> corrige y se vuelve a dejar en la carpeta, el nuevo reemplaza al anterior.

---

## Instalación (una sola vez por computadora)

1. Instalar **Python 3.11 o superior** desde <https://www.python.org/downloads/>. En la primera
   pantalla del instalador, tildar **"Add python.exe to PATH"**.
2. Copiar la carpeta `control-gestion` a la computadora (o a una carpeta compartida del estudio).
3. Abrir la carpeta, hacer clic en la barra de direcciones del Explorador, escribir `cmd` y apretar
   Enter. Se abre una ventana negra (la terminal) ya ubicada en esa carpeta.
4. Escribir y dar Enter:
   ```
   pip install -r requirements.txt
   ```
5. Controlar que todo funcione:
   ```
   python -m pytest -q
   ```
   Al final tiene que decir `passed` (todos los tests aprobados), sin `failed`.

**Para que los importes se vean como `$ 1.234.567`**, la configuración regional de Windows tiene que
ser *Español (Argentina)*: Configuración › Hora e idioma › Región. Excel toma de ahí el punto de miles
y la coma decimal.

---

## Qué archivos se cargan

Todo va en `clientes/<cliente>/entrada/AAAA-MM/`. El sistema reconoce cada archivo **por su contenido
o por su nombre**, así que no hace falta renombrar los archivos de ARCA ni los del banco.

| Archivo | De dónde sale | Obligatorio | Formato |
|---|---|---|---|
| Comprobantes **emitidos** | ARCA › Mis Comprobantes › Emitidos › Exportar CSV | Sí | Como lo baja ARCA |
| Comprobantes **recibidos** | ARCA › Mis Comprobantes › Recibidos › Exportar CSV | Sí | Como lo baja ARCA |
| **F.931** | Declaración en línea › Ver formulario › Guardar como PDF | Sí | PDF (no escaneado) |
| **Extracto bancario** | Home banking (hoy se lee el formato de Banco Galicia) | Recomendado | PDF |
| `parte_diario.csv` | Google Form del parte diario › Respuestas › Descargar CSV | No | Columnas según `kpis.yaml` |
| `saldos.csv` | A mano: saldos de cuentas sin extracto, caja, fondos de inversión | No | `fecha;cuenta;saldo` |
| `pagos_personal.csv` | A mano: lo que se le pagó a cada persona no registrada en el mes | No | `persona;monto` |
| `ventas_sin_comprobante.csv` | A mano: ventas sin factura | No | `fecha;concepto;monto` |

Notas:
- Los CSV que se cargan a mano pueden usar `;` o `,` como separador, y montos escritos como
  `1.234,56` o `1234.56`. Las fechas van en formato `dd/mm/aaaa`.
- Un CSV de ARCA puede abarcar varios meses (por ejemplo, todo el año). Si después se carga un mes
  suelto, ese mes reemplaza lo que había.
- Si el archivo de ARCA trae en el nombre el CUIT de otra empresa, **no se procesa** y sale una
  alerta. Así se evita mezclar clientes por error.
- Si falta una fuente opcional, el cierre funciona igual y los indicadores que dependen de ella
  muestran **"sin dato"** con el semáforo gris.

Ejemplos:

```
saldos.csv                        pagos_personal.csv        ventas_sin_comprobante.csv
fecha;cuenta;saldo                persona;monto             fecha;concepto;monto
30/11/2026;FIMA;3.500.000,00      Claudio;450.000           15/11/2026;Venta en fábrica;85.000
30/11/2026;Caja chica;120.000     Empleado 2;380.000
```

---

## Qué genera cada cierre

En `clientes/<cliente>/salida/AAAA-MM/`:

| Archivo | Para qué |
|---|---|
| `Tablero_<cliente>_AAAA-MM.xlsx` | El tablero completo (hojas abajo) |
| `Resumen_reunion_AAAA-MM.pdf` y `.md` | Una página para la reunión con los socios (se puede mandar por WhatsApp) |
| `alertas_AAAA-MM.csv` | Las alertas en una planilla simple |

Hojas del Excel:

| Hoja | Qué muestra |
|---|---|
| **Tablero** | Arriba, los 8 KPIs principales (★) en tarjetas, cada una con valor, meta, mes anterior, mismo mes del año anterior y semáforo. Abajo, el resto de los indicadores y la caja. |
| **Resultado mensual** | Ventas y costos por rubro, mes por mes, con el acumulado y el % sobre ventas (los totales son fórmulas). También muestra lo que queda fuera del resultado, la energía por fecha de factura y el resumen de caja y banco. |
| **Gráficos** | Ventas contra costos apilados por mes (el rubro principal en rojo) y el % del rubro principal sobre las ventas. |
| **Clientes** | Lista para llamar, clientes nuevos, clientes perdidos (más de 60 días sin comprar) y ranking. |
| **Compras** | Compras por rubro y por mes, y el detalle por proveedor con la regla que se le aplicó. |
| **Personal** | Nómina, F.931 mes por mes y escenario de regularización. Las celdas en azul se pueden cambiar para simular. |
| **Alertas** | Lo que hay que revisar, ordenado por prioridad, con la acción a tomar. |
| **Semanal** | Producción, ventas, merma y consumo por semana. Solo aparece cuando hay parte diario. |
| **Decisiones** | Tabla editable (fecha, decisión, responsable, vence, estado) que se conserva de un mes al otro. |
| **Leyenda** | Cómo leer los colores y dónde se cambian las reglas. |

Colores (los mismos de la planilla modelo del estudio):

- **Texto azul:** dato que se carga o que se puede cambiar.
- **Fondo gris:** fórmula; no hay que tocarla.
- **Fondo amarillo:** dato estimado o supuesto a revisar.

Semáforo:

- 🟢 **Verde:** cumple la meta.
- 🟡 **Amarillo:** se desvía hasta una tolerancia.
- 🔴 **Rojo:** se desvía más que la tolerancia.
- ⚪ **Gris:** no hay dato.

Además se genera la **exportación para Power BI** (ver más abajo).

---

## Clientes cargados

| Carpeta | Cliente | Comentario |
|---|---|---|
| `duclos` | DUCLOS SAS (fábrica de hielo) | Datos reales ene–oct 2026 |
| `cafe_hefesto` | Café Hefesto SRL (**cliente de prueba**) | Dado de alta con `nuevo_cliente.py`, con datos inventados ago–oct 2026. Para que no aparezca en `--todos`, poner `activo: false` en su `empresa.yaml`, o borrar la carpeta. |

## Dar de alta un cliente nuevo

```
python nuevo_cliente.py --nombre "Café Hefesto" --rubro gastronomia
```

Rubros disponibles: `fabrica`, `comercio`, `servicios`, `gastronomia` y `generico` (en la carpeta
`plantillas_rubro/`).

El comando hace preguntas en la terminal. Si la respuesta propuesta entre corchetes está bien, alcanza
con apretar Enter. Ejemplo:

```
Alta de cliente: Café Hefesto · plantilla Gastronomía
Apretá Enter para aceptar el valor entre corchetes.

Razón social [Café Hefesto]: Hefesto SRL
CUIT (con o sin guiones): 30-71234567-1
Actividad (en pocas palabras) [Vende cubiertos; ...]: Café y pastelería
Jurisdicción de IIBB [Mendoza]:
¿Qué unidad física vende? (kg, litro, cubierto, hora...) [cubierto]:
Plural de la unidad [cubiertos]:
Meses de temporada alta (números separados por coma; vacío = sin temporada): 12,1,2
Socios (separados por coma): Ana Pérez, Pedro Gómez
¿Cuántas personas están registradas (en el F.931)? [0]: 4
¿Cuántas personas trabajan SIN registrar? [0]: 1
  Nombre de la persona no registrada 1 [No registrado 1]: Pedro Ayudante
Alícuota de IIBB para 'Gastronomía' (%) [3,5]:

✔ Cliente creado en clientes\cafe_hefesto
```

El comando crea `clientes/cafe_hefesto/` con:
- `config/`: los 5 archivos de configuración, armados a partir de la plantilla del rubro;
- `entrada/`: un `LEEME.txt` y la carpeta del mes actual;
- `datos/` y `salida/`.

Después del alta conviene revisar dos cosas:
- `rubros.yaml`: agregar las reglas de los proveedores habituales del cliente;
- `kpis.yaml`: ajustar las metas.

Sin preguntas (útil para probar): agregar `--cuit 30-71234567-1 --si`.

---

## Cómo cambiar reglas, metas, impuestos y personal

Los archivos están en `clientes/<cliente>/config/` y se abren con el Bloc de notas. Cada uno explica
en su encabezado cómo se usa. **Después de cualquier cambio, volver a correr el cierre del mes.**

Reglas para editarlos sin romperlos:
- Respetar las sangrías (espacios al principio de la línea). No usar tabulaciones.
- Si un texto tiene `:`, ponerlo entre comillas.
- Si algo queda mal escrito, el cierre avisa en qué archivo y cerca de qué línea está el error.

### Reclasificar un proveedor (`rubros.yaml`)

Cuando un proveedor aparece en Alertas como "Proveedor sin regla", agregar una línea en `reglas:`.
La alerta ya trae la línea armada para copiar; solo hay que completar el rubro:

```yaml
reglas:
  - {cuit: "30708673435", rubro: Honorarios}                       # AX Sistemas (por CUIT)
  - {contiene: PINTURERIA, rubro: Mantenimiento de frío}            # por texto en el nombre
```

- Las reglas se aplican **en orden**: si un proveedor coincide con dos, gana la primera.
- Si un gasto marcado "A REVISAR" resulta ser de la empresa, se le agrega una regla **más arriba** que
  la que lo mandó a revisar.
- Para crear un rubro nuevo, sumarlo a la lista `rubros:` con su `tipo`:
  - `fijo`: se paga igual aunque se venda menos (alquiler, abono);
  - `variable`: crece con las ventas.

### Cambiar una meta o la tolerancia (`kpis.yaml`)

```yaml
- {id: energia_ventas, base: rubro_sobre_ventas, params: {rubro: Energía}, nombre: "Energía / ventas",
   estrella: true, meta: 0.40, direccion: "≤", tolerancia: 0.05}
```

- Los porcentajes se escriben en tanto por uno: `0.40` = 40 % y `0.05` = 5 puntos.
- `estrella: true` pone el KPI en las tarjetas grandes del tablero (como máximo 8).
- `activo: false` lo saca del tablero.
- Meta por temporada: `meta: {alta: [2, 4], baja: [null, 2]}`, que significa "entre 2 y 4 en
  temporada alta" y "hasta 2 en baja".
- Meta solo para algunos meses: `solo_meses: [5, 6, 7, 8]`.

### Definir el criterio de IIBB (`impuestos.yaml`)

Mientras `criterio: pendiente`:
- el tablero muestra el rango mínimo–máximo del impuesto;
- el resultado usa el máximo;
- hay una alerta pidiendo que se defina.

Cuando se defina, cambiar `criterio` por una de estas opciones:
- `tipo_comprobante`: por ejemplo, Factura A → Elaboración y Factura B → Venta;
- `lista_cuit`: los CUIT de la lista van a una actividad y el resto a la otra;
- `porcentaje`: un % fijo de las ventas para cada actividad.

### Personal (`personal.yaml`)

- Cada persona va con `registrado: true` o `registrado: false`.
- Para el escenario de regularización se puede cargar `sueldo_bruto_regularizacion: 750000`. Si no se
  carga, se usa la remuneración promedio por empleado del último F.931.
- Si una persona no registrada **factura** (Factura C), su CUIT va en `rubros.yaml` al rubro
  `Personal no registrado (facturas)`. En ese caso **no** hay que repetirla en `pagos_personal.csv`.

---

## Cierre de todos los clientes, resumen del estudio y Power BI

```
python cierre.py --todos --mes 2026-11
```

- Procesa todos los clientes con `activo: true` en `empresa.yaml`. Si un cliente tiene un problema, se
  informa y se sigue con los demás.
- Genera `estudio/salida/2026-11/Resumen_estudio_2026-11.xlsx`: una fila por cliente con sus KPIs ★ y
  el semáforo, ordenados por prioridad (más rojos y alertas altas primero). Sirve para decidir a quién
  llamar primero.
- **Power BI:** cada cierre deja en `clientes/<cliente>/powerbi/` y en `estudio/powerbi/` (todos los
  clientes juntos) las tablas en CSV y Parquet:
  - `hechos_movimientos`
  - `hechos_kpis`
  - `dim_calendario`
  - `dim_contrapartes`
  - `dim_rubros`
  - `dim_kpis`
  - `dim_empresa`

  El esquema es el mismo para todos los clientes. Hay que armar **un solo modelo de Power BI**
  apuntando a `estudio/powerbi/` y relacionar por `cliente_id`, `mes`/`fecha`, `contraparte_id`,
  `rubro` y `kpi_id`.

---

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| `No existe el cliente 'xxx'` | Revisar el nombre de la carpeta en `clientes/`. El mensaje lista los clientes que existen. |
| `El mes 'xxx' no es válido` | Escribirlo como `2026-11`. |
| `... es de otro CUIT` | El archivo es de otra empresa. Moverlo a la carpeta del cliente correcto. |
| `No puedo guardar ... el archivo está abierto` | Cerrar el Excel y volver a correr. |
| `tiene un error de formato (cerca de la línea N)` | Revisar sangrías y comillas en ese `.yaml`. |
| `no reconozco el formato de este extracto` | Es un banco que todavía no se lee. Cargar el saldo de fin de mes en `saldos.csv`. |
| Un KPI dice "sin dato" | Falta la fuente que necesita. La hoja Alertas y la columna "Cómo se calcula" dicen cuál. |

---

## Supuestos y criterios (anotados durante la construcción)

**Comprobantes**
1. **Neto** = gravado + no gravado + exento.
2. Las **notas de crédito** (tipos 3, 8, 13, 53, 113, 203, 208, 213) restan.
3. Si la moneda no es pesos, los importes se multiplican por el *Tipo Cambio* del comprobante.
4. **Comprobantes C** (tipos 11, 12, 13, 15 y 211 a 213): ARCA informa solo el total, así que **el neto
   es el total**. Sin este criterio, unos $4 M de Facturas C de Duclos quedaban en cero.
5. **Tiques de combustible** (tipo 81): la diferencia entre el total y neto + IVA son impuestos que no
   se discriminan ($1,58 M en ene–oct). El rubro toma **solo el neto** y esa diferencia se muestra
   aparte en *Resultado mensual*, en "Fuera del resultado". Esto lo decidieron ustedes.

**Clientes**

6. Los clientes se identifican **por CUIT/DNI**. Las Facturas B a consumidor final sin documento
   (22 en Duclos) no cuentan como clientes, pero sus ventas sí suman. Con este criterio salen los 596
   clientes distintos.
7. Definiciones:
   - **recurrente:** compró en alguno de los 2 meses anteriores;
   - **nuevo:** su primera compra registrada es de este mes (en el primer mes con datos queda "sin
     dato");
   - **perdido:** su última compra superó los 60 días durante este mes (el plazo es configurable);
   - **lista para llamar:** los recurrentes que no compraron este mes y los perdidos con 2 o más meses
     de compra, ordenados por lo que compraron en 12 meses.

**Energía y estimaciones**

8. **Energía a mes vencido:** la factura de EDEMSA de cada mes corresponde al consumo del mes anterior
   (`devengamiento: mes_anterior`).
   - El resultado y el KPI usan el **mes de consumo**.
   - La vista **por fecha de factura** se muestra aparte. El dato de control de $21.305.634 (58 %)
     está calculado en esta vista.
9. **Datos que todavía no llegaron:**
   - Si falta la factura del mes siguiente (por ejemplo, la luz de octubre llega en noviembre), se usa
     el valor del mes anterior y se marca como **estimado**: celda amarilla, alerta y "resultado
     provisorio".
   - Lo mismo pasa con el F.931 del último mes.
   - Se corrige solo cuando llega el dato y se vuelve a correr el cierre.
   - Se puede desactivar con `estimar_faltantes: false`.

**Costos e impuestos**

10. **Costo laboral registrado** = Rem. 1 + 351 + 352 + 312 + 028.
    - Las **cargas sociales** del KPI (IIBB + cargas) / ventas son 351 + 352 + 312 + 028
      (contribuciones patronales, ART y seguro de vida).
    - Los aportes 301 y 302 no se suman porque salen del sueldo.
11. **IIBB:**
    - Se calcula sobre las ventas facturadas netas.
    - Con el criterio "pendiente", el resultado usa la alícuota **máxima** (3,5 %) por prudencia, y
      el rango se muestra aparte.
12. **Gastos que solo aparecen en el banco:**
    - El impuesto al cheque (Ley 25.413) y el impuesto de sellos van a *Impuestos y tasas*.
    - Los intereses por saldo deudor van a *Bancos*.
    - Las **comisiones bancarias no se toman del extracto**, porque el banco las factura (comprobante
      63) y se duplicarían. Consecuencia: en ene–jun de Duclos (antes de que aparezcan esas facturas)
      faltan unos $55–60 mil por mes de comisiones.

**Caja y bancos**

13. **Caja:**
    - Es el saldo bancario de fin de mes (último movimiento del extracto), más los saldos de
      `saldos.csv`, más el efectivo del parte diario.
    - Los **fondos de inversión** (FIMA, FCI, plazo fijo) **no son caja**: se muestran aparte si se
      carga su saldo. Mientras tanto se informa el movimiento neto de suscripciones y rescates.
    - El extracto puede cerrar antes del fin de mes (por ejemplo, el 29/05).
14. **Gasto fijo diario** = promedio de los últimos 3 meses de (rubros `fijo` + costo laboral total),
    dividido 30.
15. **Depósitos en efectivo** en el banco: se marcan como alerta de "posibles ventas sin comprobante".
    Esto lo decidieron ustedes.
16. **Saldo deudor de Galicia:** el banco escribe el signo al final (`23.357,35-`). Se lee como negativo.

**Duclos en particular**

17. Clasificación de rubros:
    - Energía, combustible y reparto, y envases: **variables**.
    - Mantenimiento de frío, telecomunicaciones, bancos e impuestos y tasas: **fijos**.
18. **Claudio Fabián Díaz Villegas** es personal no registrado (lo confirmaron ustedes). Sus
    Facturas C suman al costo laboral, no a compras.
    - El segundo no registrado figura como "Empleado no registrado 2" hasta que se cargue su nombre.
    - Mientras no haya `pagos_personal.csv`, el costo laboral está subestimado y hay una alerta.
19. **Escenario de regularización:**
    - Sueldo bruto: el de `personal.yaml` o, si no hay, el Rem. 1 promedio del último F.931.
    - Contribuciones: el mismo % efectivo de ese F.931 (34,6 % en septiembre).
    - Incluye el aguinaldo prorrateado (13/12). No incluye indemnizaciones ni deuda de períodos
      anteriores.
    - El "pago actual" es el promedio de los últimos 3 meses con pagos cargados.
20. **Proveedores sin regla:** quedan en A REVISAR, fuera del resultado, hasta que se clasifiquen. Esto
    lo decidieron ustedes.
21. **Tolerancias de las metas:** ustedes dieron las metas pero no las tolerancias. Las propuse yo y se
    pueden editar en `kpis.yaml`:

    | KPI | Tolerancia |
    |---|---|
    | Energía / ventas | 5 puntos |
    | Reparto / ventas | 3 puntos |
    | Resultado operativo | $300.000 |
    | Merma | 1 punto |
    | Cobertura de stock | 1 día |
    | Caja | 10 días |
    | Ventas may–ago | $500.000 |
    | (IIBB + cargas) / ventas | 3 puntos |
    | Gastos A REVISAR | 0 (cualquier monto es rojo) |

22. **Socios:** los nombres no están cargados (figuran "Socio 1" y "Socio 2" en `empresa.yaml`).
23. **Datos parciales:** los CSV de ARCA llegan hasta el 24/10/2026, así que octubre está incompleto.
    Faltan el F.931 de octubre y los extractos de septiembre y octubre (la caja de esos meses queda
    "sin dato").

**Funcionamiento del sistema**

24. **Decisiones:** al generar un tablero se toma la hoja *Decisiones* del Excel modificado más
    recientemente entre los meses anteriores o iguales al del cierre. Se guarda una copia en
    `datos/decisiones.csv`.
25. **Histórico:**
    - `datos/historico.parquet` acumula todo y no se borra.
    - Cada cierre lee solo los archivos nuevos o modificados (según `datos/archivos_procesados.json`).
    - Si cambia un archivo de una carpeta, se releen esa carpeta y las posteriores.
    - Para releer todo, borrar `historico.parquet`.

---

## Para quien mantenga el código

```
control-gestion/
  cierre.py              cierre mensual (--cliente / --todos)
  nuevo_cliente.py       alta de cliente con preguntas guiadas
  plantillas_rubro/      generico.yaml + fabrica/comercio/servicios/gastronomia (heredan de generico)
  clientes/<cliente>/    config/ · entrada/AAAA-MM/ · datos/ · salida/AAAA-MM/ · powerbi/
  estudio/               resumen del estudio y Power BI consolidado
  referencia/            planilla modelo (solo referencia de estilo)
  src/
    lectores/            arca.py · f931.py · bancos.py · opcionales.py · pdf.py (comunes a todos)
    historico.py         base acumulada sin duplicados
    clasificador.py      proveedor → rubro
    personal.py          registrado / no registrado / regularización
    contexto.py          series mensuales que usan los KPIs
    biblioteca_kpis.py   cada KPI definido una sola vez (nombre, fórmula, fuente, unidad, sin dato)
    motor_kpis.py        metas por temporada y semáforo
    alertas.py
    reportes/            excel.py · resumen.py · powerbi.py · estudio.py · decisiones.py
  tests/                 aceptación con datos reales de Duclos + cliente sintético de gastronomía
```

- Para **agregar un KPI**: sumar una función y un `KPIDef` en `src/biblioteca_kpis.py`, y activarlo en
  el `kpis.yaml` de cada cliente.
- Para **agregar un banco**: sumar un intérprete en `FORMATOS` de `src/lectores/bancos.py`.
- `tests/test_cierre.py::test_codigo_sin_datos_de_un_cliente` falla si aparece algo de un cliente
  dentro del código.
