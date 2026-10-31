"""Cliente ficticio de gastronomía con datos sintéticos (para probar que nada de Duclos quedó en el código).

Genera, en una base temporal, los mismos tipos de archivo que deja el estudio: CSV de ARCA emitidos y
recibidos, F.931 en PDF, parte diario, saldos y pagos a personal no registrado. Devuelve los valores
esperados calculados a mano.
"""
from __future__ import annotations

from pathlib import Path

CUIT = "30712345671"   # dígito verificador correcto
MESES = ["2026-01", "2026-02", "2026-03"]

CAB_EMI = ["Fecha de Emisión", "Tipo de Comprobante", "Punto de Venta", "Número Desde", "Número Hasta",
           "Cód. Autorización", "Tipo Doc. Receptor", "Nro. Doc. Receptor", "Denominación Receptor", "Tipo Cambio",
           "Moneda", "Imp. Neto Gravado IVA 0%", "IVA 2,5%", "Imp. Neto Gravado IVA 2,5%", "IVA 5%",
           "Imp. Neto Gravado IVA 5%", "IVA 10,5%", "Imp. Neto Gravado IVA 10,5%", "IVA 21%",
           "Imp. Neto Gravado IVA 21%", "IVA 27%", "Imp. Neto Gravado IVA 27%", "Imp. Neto Gravado Total",
           "Imp. Neto No Gravado", "Imp. Op. Exentas", "Otros Tributos", "Total IVA", "Imp. Total"]
CAB_REC = (CAB_EMI[:6] + ["Tipo Doc. Emisor", "Nro. Doc. Emisor", "Denominación Emisor", "Tipo Doc. Receptor",
                          "Nro. Doc. Receptor"] + CAB_EMI[9:])

CLIENTES = [("20111111112", "PEREZ ANA"), ("27222222223", "GOMEZ LUIS"), ("30333333334", "EVENTOS SRL")]
PROVEEDORES = {
    "frigo": ("30500000001", "FRIGORIFICO DEL SUR SA", 1, 300000.0),      # Materia prima (regla FRIGORIF)
    "cerve": ("30500000002", "CERVECERIA ANDINA SA", 1, 100000.0),        # Bebidas (regla CERVECER)
    "gas": ("30500000003", "ECOGAS DISTRIBUIDORA DE GAS CUYANA", 17, 80000.0),  # Energía
    "inmo": ("30500000004", "INMOBILIARIA SIN REGLA SRL", 1, 200000.0),   # sin regla -> A REVISAR
}
F931 = {"empleados": 3, "rem1": 1500000.0, "301": 165000.0, "302": 45000.0, "351": 300000.0,
        "352": 90000.0, "312": 60000.0, "028": 1000.0}
COSTO_931 = F931["rem1"] + F931["351"] + F931["352"] + F931["312"] + F931["028"]


def _n(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _ar(v: float) -> str:
    s = f"{v:,.2f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _fila_emi(fecha, tipo, nro, doc, nombre, neto, moneda="$", tc=1.0):
    iva = round(neto * 0.21, 2)
    return [fecha, str(tipo), "3", str(nro), str(nro), "7600000000000" + str(nro), "80" if doc else "",
            doc, nombre, _n(tc), moneda, "", "", "", "", "", "", "", _n(iva), _n(neto), "", "", _n(neto),
            "0,00", "0,00", "0,00", _n(iva), _n(neto + iva)]


def _fila_rec(fecha, tipo, nro, doc, nombre, neto):
    if tipo == 11:  # Factura C: ARCA informa sólo el total
        return [fecha, "11", "2", str(nro), str(nro), "", "80", doc, nombre, "80", CUIT, "1,00", "$"] + \
            ["0,00"] * 12 + ["0,00", "0,00", "0,00", "0,00", _n(neto)]
    iva = round(neto * 0.21, 2)
    return [fecha, str(tipo), "2", str(nro), str(nro), "", "80", doc, nombre, "80", CUIT, "1,00", "$"] + \
        ["0,00"] * 7 + [_n(iva), _n(neto), "0,00", "0,00", _n(neto), "0,00", "0,00", "0,00", _n(iva), _n(neto + iva)]


def _csv(ruta: Path, cab, filas):
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(";".join(f'"{c}"' for c in cab) + "\n")
        for r in filas:
            f.write(";".join(r) + "\n")


def _f931_pdf(ruta: Path, mes: str):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(ruta), pagesize=A4)
    lineas = [
        "Declaración en línea Formulario F.931",
        f"C.U.I.T. {CUIT[:2]}-{CUIT[2:10]}-{CUIT[10]}",
        "Mes - Año Orig. (0) - Rect. (1/9): 0",
        f"{mes[5:]}/{mes[:4]} Servicios Eventuales: No",
        f"Empleados en nómina: {F931['empleados']}",
        f"Suma de Rem. 1: {_ar(F931['rem1'])}",
        f"Suma de Rem. 2: {_ar(F931['rem1'])}",
        "VIII - MONTOS QUE SE INGRESAN",
        f"301 - Aportes de Seguridad Social {_ar(F931['301'])} 302 - Aportes de Obra Social {_ar(F931['302'])}",
        f"351 - Contribuciones de Seguridad Social {_ar(F931['351'])} 352 - Contribuciones de Obra Social {_ar(F931['352'])}",
        f"360 - Contribuciones RENATRE 0,00 312 - L.R.T. {_ar(F931['312'])}",
        f"028 - Seguro Colectivo de Vida Obligatorio {_ar(F931['028'])} 270 - Vales Alimentarios 0,00",
    ]
    y = 800
    for linea in lineas:
        c.drawString(40, y, linea)
        y -= 16
    c.save()


def generar(base: Path, meses=MESES, carpeta: Path | None = None) -> dict:
    """Crea el cliente con nuevo_cliente.py (sin preguntas) y le carga 3 meses de datos.
    Si se pasa `carpeta`, usa un cliente ya creado (con CUIT = CUIT de este módulo)."""
    import nuevo_cliente
    import yaml
    if carpeta is None:
        carpeta = nuevo_cliente.crear(base, "Café Prueba Sintética", "gastronomia",
                                      nuevo_cliente.Preguntas(False), cuit=CUIT)
    # Una persona no registrada (como haría el estudio editando personal.yaml)
    pers_f = carpeta / "config" / "personal.yaml"
    pers = yaml.safe_load(pers_f.read_text(encoding="utf-8"))
    pers["personas"] = [{"nombre": f"Registrado {i}", "registrado": True} for i in range(1, 4)] + \
        [{"nombre": "Juan Perez", "registrado": False, "sueldo_bruto_regularizacion": 600000}]
    pers_f.write_text(yaml.safe_dump(pers, allow_unicode=True), encoding="utf-8")

    esperado = {"ventas": {}, "costos": {}, "revisar": {}, "unidades": {}}
    emi, rec, nro = [], [], 100
    for k, mes in enumerate(meses):
        ventas = 0.0
        for j, (doc, nom) in enumerate(CLIENTES):
            neto = 500000.0 + 100000.0 * j + 50000.0 * k
            nro += 1
            emi.append(_fila_emi(f"{mes}-10", 6, nro, doc, nom, neto))
            ventas += neto
        nro += 1
        emi.append(_fila_emi(f"{mes}-15", 6, nro, "", "", 120000.0))   # consumidor final anónimo
        ventas += 120000.0
        if k == 1:
            nro += 1
            emi.append(_fila_emi(f"{mes}-20", 8, nro, CLIENTES[0][0], CLIENTES[0][1], 50000.0))  # NC resta
            ventas -= 50000.0
            nro += 1
            emi.append(_fila_emi(f"{mes}-21", 1, nro, "30444444445", "EXPORT SA", 100.0, "DOL", 1000.0))  # USD
            ventas += 100000.0
        esperado["ventas"][mes] = ventas
        for clave, (doc, nom, tipo, neto) in PROVEEDORES.items():
            nro += 1
            rec.append(_fila_rec(f"{mes}-05", tipo, nro, doc, nom, neto))
        revisar = PROVEEDORES["inmo"][3]
        if k == 1:
            nro += 1
            rec.append(_fila_rec(f"{mes}-12", 11, nro, "20555555556", "OPTICA LUZ", 50000.0))  # patrón -> A REVISAR
            revisar += 50000.0
        esperado["revisar"][mes] = revisar
        esperado["costos"][mes] = {"Materia prima e insumos": 300000.0, "Bebidas": 100000.0, "Energía": 80000.0}

        d = carpeta / "entrada" / mes
        d.mkdir(parents=True, exist_ok=True)
        _f931_pdf(d / f"{mes[5:]}.{mes[:4]}_F.931.pdf", mes)
        # Parte diario: 100 cubiertos por día, 110 platos preparados, 3 descartados
        import calendar
        dias = calendar.monthrange(int(mes[:4]), int(mes[5:]))[1]
        with open(d / "parte_diario.csv", "w", encoding="utf-8") as f:
            f.write("Marca temporal,fecha,cubiertos,platos_preparados,platos_descartados,caja_efectivo\n")
            for dia in range(1, dias + 1):
                f.write(f"{dia:02d}/{mes[5:]}/{mes[:4]} 23:00:00,{dia:02d}/{mes[5:]}/{mes[:4]},100,110,3,"
                        f"{'150000' if dia == dias else '90000'}\n")
        esperado["unidades"][mes] = 100 * dias
        esperado.setdefault("descartadas", {})[mes] = 3 * dias
        esperado.setdefault("producidas", {})[mes] = 110 * dias
    # Último mes: pagos a no registrados y saldos (con un fondo de inversión que NO es caja)
    d = carpeta / "entrada" / meses[-1]
    (d / "pagos_personal.csv").write_text("persona;monto\nJuan Perez;400.000\n", encoding="utf-8")
    import calendar
    fin = f"{calendar.monthrange(int(meses[-1][:4]), int(meses[-1][5:]))[1]}/{meses[-1][5:]}/{meses[-1][:4]}"
    (d / "saldos.csv").write_text(f"fecha;cuenta;saldo\n{fin};Banco Nación CC;2.000.000,00\n"
                                  f"{fin};FCI Money Market;5.000.000,00\n", encoding="utf-8")
    d0 = carpeta / "entrada" / meses[0]
    _csv(d0 / f"comprobantes_consulta_csv_emitidos_1_{CUIT}_x.csv", CAB_EMI, emi)
    _csv(d0 / f"comprobantes_consulta_csv_recibidos_1_{CUIT}_x.csv", CAB_REC, rec)
    esperado.update({"id": carpeta.name, "carpeta": carpeta, "costo_931": COSTO_931, "pago_nr": 400000.0,
                     "caja_mar": 2000000.0 + 150000.0, "inversiones_mar": 5000000.0, "alicuota": 0.035})
    return esperado
