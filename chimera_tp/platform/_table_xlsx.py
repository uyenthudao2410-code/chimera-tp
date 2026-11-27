"""Write one Office Open XML worksheet of literal Unicode text cells."""

from __future__ import annotations

import io
import re
from xml.etree import ElementTree as ET
import zipfile

_SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
_XML = "http://www.w3.org/XML/1998/namespace"
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _column(index):
    chars = []
    while index:
        index, offset = divmod(index - 1, 26)
        chars.append(chr(ord("A") + offset))
    return "".join(reversed(chars))


def _relationships(rel_type, target):
    root = ET.Element("Relationships", xmlns=_REL)
    ET.SubElement(root, "Relationship", Id="rId1", Type=_DOC + "/" + rel_type, Target=target)
    return root


def text_workbook(rows):
    if len(rows) > 1048576 or any(len(row) > 16384 for row in rows):
        raise ValueError("worksheet exceeds Excel's row or column limit")
    types = ET.Element("Types", xmlns=_CONTENT)
    ET.SubElement(types, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    ET.SubElement(types, "Default", Extension="xml", ContentType="application/xml")
    prefix = "application/vnd.openxmlformats-officedocument.spreadsheetml."
    for part, kind in (("/xl/workbook.xml", "sheet.main"), ("/xl/worksheets/sheet1.xml", "worksheet")):
        ET.SubElement(types, "Override", PartName=part, ContentType=prefix + kind + "+xml")
    workbook = ET.Element("workbook", {"xmlns": _SHEET, "xmlns:r": _DOC})
    sheets = ET.SubElement(workbook, "sheets")
    ET.SubElement(sheets, "sheet", {"name": "Sheet", "sheetId": "1", "r:id": "rId1"})
    worksheet = ET.Element("worksheet", xmlns=_SHEET)
    data = ET.SubElement(worksheet, "sheetData")
    for index, values in enumerate(rows, 1):
        row = ET.SubElement(data, "row", r=str(index))
        for column, value in enumerate(values, 1):
            if len(value) > 32767 or _ILLEGAL.search(value):
                raise ValueError("cell exceeds Excel's text limit or contains an illegal XML character")
            cell = ET.SubElement(row, "c", r=f"{_column(column)}{index}", t="inlineStr")
            text = ET.SubElement(ET.SubElement(cell, "is"), "t", {"{" + _XML + "}space": "preserve"})
            text.text = value
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        parts = {"[Content_Types].xml": types, "_rels/.rels": _relationships("officeDocument", "xl/workbook.xml"),
                 "xl/workbook.xml": workbook, "xl/worksheets/sheet1.xml": worksheet,
                 "xl/_rels/workbook.xml.rels": _relationships("worksheet", "worksheets/sheet1.xml")}
        for name, tree in parts.items():
            xml = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
            # Character references preserve literal carriage returns across XML normalization.
            archive.writestr(name, xml.replace(b"\r", b"&#13;"))
    return out.getvalue()
