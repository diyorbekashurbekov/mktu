"""Minimal, dependency-free .xlsx reader (zipfile + ElementTree).

Returns every sheet as a list of rows with their real Excel row numbers so that
every computed figure can be traced back to "sheet!row".
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

MAX_UNCOMPRESSED = 60 * 1024 * 1024  # zip-bomb guard
MAX_ENTRIES = 2000


class XlsxError(ValueError):
    """The uploaded file is not a readable .xlsx workbook."""


def _safe_xml(raw: bytes) -> ET.Element:
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
        raise XlsxError("XML ішінде DOCTYPE/ENTITY бар — файл қабылданбайды")
    return ET.fromstring(raw)


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _convert(text: str | None):
    if text is None or text == "":
        return None
    try:
        num = float(text)
    except ValueError:
        return text
    if num.is_integer() and "e" not in text.lower() and abs(num) < 2**53:
        return int(num)
    return num


def read_workbook(data: bytes) -> dict[str, list[dict]]:
    """Parse workbook bytes -> {sheet_name: [{"row": n, "cells": [values...]}]}"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError("Файл .xlsx форматында емес (zip архиві ашылмады)") from exc

    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        raise XlsxError("Файл тым үлкен немесе күдікті құрылымды")
    names = set(zf.namelist())
    if "xl/workbook.xml" not in names:
        raise XlsxError("xl/workbook.xml табылмады — бұл Excel кітабы емес")

    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in _safe_xml(zf.read("xl/sharedStrings.xml")).iter(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))

    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in _safe_xml(zf.read("xl/_rels/workbook.xml.rels")).iter(PKG_REL_NS + "Relationship"):
            rels[rel.get("Id")] = rel.get("Target")

    workbook = _safe_xml(zf.read("xl/workbook.xml"))
    result: dict[str, list[dict]] = {}
    for sheet in workbook.iter(NS + "sheet"):
        target = rels.get(sheet.get(REL_NS + "id"), "")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        if path not in names:
            continue
        rows = []
        for row in _safe_xml(zf.read(path)).iter(NS + "row"):
            cells: list = []
            for cell in row.iter(NS + "c"):
                ref = cell.get("r")
                col = _col_index(ref) if ref else len(cells)
                ctype = cell.get("t")
                v = cell.find(NS + "v")
                if ctype == "s" and v is not None:
                    value = shared[int(v.text)]
                elif ctype == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter(NS + "t"))
                elif ctype == "str":
                    value = v.text if v is not None else None
                elif ctype == "b":
                    value = bool(int(v.text)) if v is not None else None
                else:
                    value = _convert(v.text if v is not None else None)
                if isinstance(value, str):
                    value = value.strip()
                    if value == "":
                        value = None
                while len(cells) < col:
                    cells.append(None)
                cells.append(value)
            if any(c is not None for c in cells):
                rows.append({"row": int(row.get("r", len(rows) + 1)), "cells": cells})
        result[sheet.get("name")] = rows
    if not result:
        raise XlsxError("Кітапта оқылатын парақтар жоқ")
    return result
