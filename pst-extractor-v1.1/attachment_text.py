from __future__ import annotations

import csv
import html
import io
import os
import posixpath
import re
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

TEXT_EXTS = {'.txt', '.md', '.csv', '.tsv', '.log', '.json', '.xml', '.yaml', '.yml'}
WORD_EXTS = {'.docx', '.docm', '.dotx', '.dotm'}
EXCEL_EXTS = {'.xlsx', '.xlsm', '.xltx', '.xltm'}
PPT_EXTS = {'.pptx', '.pptm', '.ppsx', '.ppsm', '.potx', '.potm'}
PDF_EXTS = {'.pdf'}
RTF_EXTS = {'.rtf'}
MSG_EXTS = {'.msg'}
LEGACY_OFFICE_EXTS = {'.doc', '.xls', '.ppt'}
SUPPORTED_EXTS = TEXT_EXTS | WORD_EXTS | EXCEL_EXTS | PPT_EXTS | PDF_EXTS | RTF_EXTS | MSG_EXTS | LEGACY_OFFICE_EXTS

NS_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS_P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
NS_S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def normalize_text(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    return text.strip()


def qn(ns: str, name: str) -> str:
    return f'{{{ns}}}{name}'


def local_name(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def read_xml_from_zip(zf: zipfile.ZipFile, name: str) -> Optional[ET.Element]:
    try:
        with zf.open(name) as f:
            return ET.parse(f).getroot()
    except (KeyError, ET.ParseError):
        return None


def resolve_target(base_part: str, target: str) -> str:
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def decode_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig'), 'utf-8-sig'
    if raw.startswith(b'\xff\xfe\x00\x00') or raw.startswith(b'\x00\x00\xfe\xff'):
        return raw.decode('utf-32'), 'utf-32'
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        return raw.decode('utf-16'), 'utf-16'
    for enc in ('utf-8', 'cp932', 'shift_jis', 'euc_jp'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    try:
        from charset_normalizer import from_bytes  # type: ignore
        best = from_bytes(raw).best()
        if best is not None:
            return str(best), best.encoding or 'charset-normalizer'
    except Exception:
        pass
    return raw.decode('latin-1', errors='replace'), 'latin-1-fallback'


class _HTMLText(HTMLParser):
    BLOCK = {'p', 'div', 'li', 'tr', 'table', 'section', 'article', 'header', 'footer', 'br', 'hr'}
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {'script', 'style', 'head'}:
            self.skip += 1
        elif not self.skip and tag in self.BLOCK:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {'script', 'style', 'head'} and self.skip:
            self.skip -= 1
        elif not self.skip and tag in self.BLOCK:
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    p = _HTMLText()
    try:
        p.feed(value)
        return normalize_text(html.unescape(''.join(p.parts)))
    except Exception:
        return normalize_text(re.sub(r'<[^>]+>', ' ', value))


def _word_para(p: ET.Element) -> str:
    out: list[str] = []
    for n in p.iter():
        if n.tag == qn(NS_W, 't') and n.text:
            out.append(n.text)
        elif n.tag == qn(NS_W, 'tab'):
            out.append('\t')
        elif n.tag in {qn(NS_W, 'br'), qn(NS_W, 'cr')}:
            out.append('\n')
    return ''.join(out).strip()


def _word_blocks(parent: ET.Element):
    for child in list(parent):
        ln = local_name(child.tag)
        if ln == 'p':
            t = _word_para(child)
            if t:
                yield t
        elif ln == 'tbl':
            for tr in child.findall(f'.//{{{NS_W}}}tr'):
                cells: list[str] = []
                for tc in tr.findall(qn(NS_W, 'tc')):
                    chunks = [_word_para(p) for p in tc.findall(f'.//{{{NS_W}}}p')]
                    cells.append(' / '.join(x for x in chunks if x))
                if any(cells):
                    yield '\t'.join(cells)
        else:
            yield from _word_blocks(child)


def extract_word(path: Path) -> str:
    lines: list[str] = []
    with zipfile.ZipFile(path, 'r') as zf:
        root = read_xml_from_zip(zf, 'word/document.xml')
        if root is None:
            raise ValueError('word/document.xml not found')
        body = root.find(qn(NS_W, 'body')) or root
        lines.extend(_word_blocks(body))
        for part in sorted(n for n in zf.namelist() if (n.startswith('word/header') or n.startswith('word/footer')) and n.endswith('.xml')):
            r = read_xml_from_zip(zf, part)
            if r is not None:
                content = list(_word_blocks(r))
                if content:
                    lines.append(f'[{Path(part).stem.upper()}]')
                    lines.extend(content)
        for part, label, item_tag in [
            ('word/footnotes.xml', 'FOOTNOTES', 'footnote'),
            ('word/endnotes.xml', 'ENDNOTES', 'endnote'),
            ('word/comments.xml', 'COMMENTS', 'comment'),
        ]:
            r = read_xml_from_zip(zf, part)
            if r is None:
                continue
            vals = []
            for item in r.findall(f'.//{{{NS_W}}}{item_tag}'):
                t = '\n'.join(_word_blocks(item)).strip()
                if t:
                    vals.append(t)
            if vals:
                lines.append(f'[{label}]')
                lines.extend(vals)
    return normalize_text('\n'.join(lines))


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    r = read_xml_from_zip(zf, 'xl/sharedStrings.xml')
    if r is None:
        return []
    out = []
    for si in r.findall(qn(NS_S, 'si')):
        out.append(''.join(t.text or '' for t in si.iter(qn(NS_S, 't'))))
    return out


def _sheet_map(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb = read_xml_from_zip(zf, 'xl/workbook.xml')
    rels = read_xml_from_zip(zf, 'xl/_rels/workbook.xml.rels')
    if wb is None:
        raise ValueError('xl/workbook.xml not found')
    rel_map = {}
    if rels is not None:
        for rel in rels.findall(qn(NS_REL, 'Relationship')):
            rid, target = rel.attrib.get('Id', ''), rel.attrib.get('Target', '')
            if rid and target:
                rel_map[rid] = resolve_target('xl/workbook.xml', target)
    result = []
    sheets = wb.find(qn(NS_S, 'sheets'))
    if sheets is not None:
        for sheet in sheets.findall(qn(NS_S, 'sheet')):
            name = sheet.attrib.get('name', '(unnamed)')
            rid = sheet.attrib.get(qn(NS_R, 'id'), '')
            target = rel_map.get(rid)
            if target:
                result.append((name, target))
    return result


def extract_excel(path: Path, include_formulas: bool = False) -> str:
    lines: list[str] = []
    with zipfile.ZipFile(path, 'r') as zf:
        shared = _shared_strings(zf)
        for sheet_name, part in _sheet_map(zf):
            root = read_xml_from_zip(zf, part)
            if root is None:
                continue
            lines.append(f'[SHEET] {sheet_name}')
            sheet_data = root.find(qn(NS_S, 'sheetData'))
            if sheet_data is None:
                continue
            for row in sheet_data.findall(qn(NS_S, 'row')):
                vals: list[str] = []
                for c in row.findall(qn(NS_S, 'c')):
                    ref = c.attrib.get('r', '')
                    typ = c.attrib.get('t', '')
                    v = c.find(qn(NS_S, 'v'))
                    f = c.find(qn(NS_S, 'f'))
                    value = ''
                    if typ == 'inlineStr':
                        value = ''.join(t.text or '' for t in c.iter(qn(NS_S, 't')))
                    elif v is not None and v.text is not None:
                        raw = v.text
                        if typ == 's':
                            try:
                                value = shared[int(raw)]
                            except Exception:
                                value = raw
                        elif typ == 'b':
                            value = 'TRUE' if raw == '1' else 'FALSE'
                        else:
                            value = raw
                    if include_formulas and f is not None and f.text:
                        value = (value + f' [formula={f.text}]').strip()
                    if value:
                        vals.append(f'{ref}={value.replace(chr(10), "\\n")}')
                if vals:
                    lines.append(' | '.join(vals))
    return normalize_text('\n'.join(lines))


def _ppt_slide_parts(zf: zipfile.ZipFile) -> list[str]:
    pres = read_xml_from_zip(zf, 'ppt/presentation.xml')
    rels = read_xml_from_zip(zf, 'ppt/_rels/presentation.xml.rels')
    if pres is None:
        raise ValueError('ppt/presentation.xml not found')
    rel_map = {}
    if rels is not None:
        for rel in rels.findall(qn(NS_REL, 'Relationship')):
            rid, target = rel.attrib.get('Id', ''), rel.attrib.get('Target', '')
            if rid and target:
                rel_map[rid] = resolve_target('ppt/presentation.xml', target)
    out: list[str] = []
    ids = pres.find(qn(NS_P, 'sldIdLst'))
    if ids is not None:
        for sld in ids.findall(qn(NS_P, 'sldId')):
            target = rel_map.get(sld.attrib.get(qn(NS_R, 'id'), ''))
            if target:
                out.append(target)
    return out or sorted(n for n in zf.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n))


def _ppt_text(root: ET.Element) -> list[str]:
    out: list[str] = []
    for p in root.iter(qn(NS_A, 'p')):
        t = ''.join(x.text or '' for x in p.iter(qn(NS_A, 't'))).strip()
        if t:
            out.append(t)
    return out


def _notes_part(zf: zipfile.ZipFile, slide_part: str) -> str:
    rel_part = posixpath.join(posixpath.dirname(slide_part), '_rels', posixpath.basename(slide_part) + '.rels')
    r = read_xml_from_zip(zf, rel_part)
    if r is None:
        return ''
    for rel in r.findall(qn(NS_REL, 'Relationship')):
        if rel.attrib.get('Type', '').endswith('/notesSlide'):
            return resolve_target(slide_part, rel.attrib.get('Target', ''))
    return ''


def extract_powerpoint(path: Path) -> str:
    lines: list[str] = []
    with zipfile.ZipFile(path, 'r') as zf:
        for idx, part in enumerate(_ppt_slide_parts(zf), 1):
            root = read_xml_from_zip(zf, part)
            if root is None:
                continue
            txt = _ppt_text(root)
            if txt:
                lines.append(f'[SLIDE {idx}]')
                lines.extend(txt)
            np = _notes_part(zf, part)
            if np:
                nr = read_xml_from_zip(zf, np)
                if nr is not None:
                    notes = _ppt_text(nr)
                    if notes:
                        lines.append(f'[NOTES {idx}]')
                        lines.extend(notes)
    return normalize_text('\n'.join(lines))


def extract_pdf(path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as e:
        raise RuntimeError('pypdf is required for PDF extraction') from e
    reader = PdfReader(str(path))
    lines: list[str] = []
    text_pages = 0
    for idx, page in enumerate(reader.pages, 1):
        try:
            text = normalize_text(page.extract_text() or '')
        except Exception as e:
            lines.append(f'[PAGE {idx} ERROR: {type(e).__name__}]')
            continue
        if text:
            text_pages += 1
            lines.append(f'[PAGE {idx}]')
            lines.append(text)
    if text_pages == 0:
        return '', 'NO_TEXT_LAYER'
    return normalize_text('\n'.join(lines)), 'OK'


def extract_rtf(path: Path) -> str:
    """Extract only visible text from RTF; discard formatting and embedded objects."""
    try:
        from striprtf.striprtf import rtf_to_text  # type: ignore
    except Exception as e:
        raise RuntimeError('striprtf is required for RTF extraction') from e
    raw = path.read_bytes()
    source = raw.decode('latin-1', errors='ignore')
    try:
        text = rtf_to_text(source, errors='ignore')
    except TypeError:
        text = rtf_to_text(source)
    return normalize_text(text)


def _safe_msg_attr(obj, name: str, default=''):
    try:
        v = getattr(obj, name, default)
        return v if v is not None else default
    except Exception:
        return default


def extract_msg(path: Path, max_depth: int = 4, depth: int = 0) -> str:
    if depth > max_depth:
        return '[MSG NESTING LIMIT REACHED]'
    try:
        import extract_msg  # type: ignore
    except Exception as e:
        raise RuntimeError('extract-msg is required for .msg attachments') from e
    lines: list[str] = []
    msg = extract_msg.Message(str(path))
    try:
        for label, attr in [('Subject', 'subject'), ('From', 'sender'), ('To', 'to'), ('Cc', 'cc'), ('Date', 'date')]:
            v = str(_safe_msg_attr(msg, attr, '')).strip()
            if v:
                lines.append(f'{label}: {v}')
        body = normalize_text(str(_safe_msg_attr(msg, 'body', '') or ''))
        if not body:
            html_body = _safe_msg_attr(msg, 'htmlBody', b'')
            if isinstance(html_body, bytes):
                html_body, _ = decode_bytes(html_body)
            body = html_to_text(str(html_body)) if html_body else ''
        if body:
            lines.append('')
            lines.append(body)
        atts = _safe_msg_attr(msg, 'attachments', []) or []
        for i, att in enumerate(atts, 1):
            name = str(_safe_msg_attr(att, 'longFilename', '') or _safe_msg_attr(att, 'shortFilename', '') or f'attachment_{i}')
            data = _safe_msg_attr(att, 'data', b'')
            if isinstance(data, bytes) and data:
                suffix = Path(name).suffix.lower()
                if suffix in SUPPORTED_EXTS:
                    with tempfile.TemporaryDirectory(prefix='pstx_msg_') as td:
                        p = Path(td) / (Path(name).name or f'att_{i}{suffix}')
                        p.write_bytes(data)
                        try:
                            text, status = extract_attachment_path(p, include_formulas=False, legacy_office=False, msg_depth=depth + 1)
                            if text:
                                lines.append(f'\n[ATTACHMENT {i}: {name}]')
                                lines.append(text)
                        except Exception:
                            pass
    finally:
        try:
            msg.close()
        except Exception:
            pass
    return normalize_text('\n'.join(lines))


def _convert_legacy(path: Path, out_dir: Path) -> Path:
    if os.name != 'nt':
        raise RuntimeError('Legacy Office conversion requires Windows + Microsoft Office')
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except Exception as e:
        raise RuntimeError('pywin32 is required for legacy Office attachments') from e
    pythoncom.CoInitialize()
    ext = path.suffix.lower()
    try:
        if ext == '.doc':
            out = out_dir / (path.stem + '.docx')
            app = win32com.client.DispatchEx('Word.Application')
            try:
                app.Visible = False; app.DisplayAlerts = 0
                try: app.AutomationSecurity = 3
                except Exception: pass
                doc = app.Documents.Open(str(path), ReadOnly=True, AddToRecentFiles=False, Visible=False)
                try: doc.SaveAs2(str(out), FileFormat=16)
                finally: doc.Close(False)
            finally: app.Quit()
            return out
        if ext == '.xls':
            out = out_dir / (path.stem + '.xlsx')
            app = win32com.client.DispatchEx('Excel.Application')
            try:
                app.Visible = False; app.DisplayAlerts = False
                try: app.AutomationSecurity = 3
                except Exception: pass
                wb = app.Workbooks.Open(str(path), ReadOnly=True, UpdateLinks=0)
                try: wb.SaveAs(str(out), FileFormat=51)
                finally: wb.Close(False)
            finally: app.Quit()
            return out
        if ext == '.ppt':
            out = out_dir / (path.stem + '.pptx')
            app = win32com.client.DispatchEx('PowerPoint.Application')
            try:
                pres = app.Presentations.Open(str(path), WithWindow=False, ReadOnly=True)
                try: pres.SaveAs(str(out), 24)
                finally: pres.Close()
            finally: app.Quit()
            return out
    finally:
        try: pythoncom.CoUninitialize()
        except Exception: pass
    raise RuntimeError(f'Unsupported legacy extension: {ext}')


def extract_attachment_path(path: Path, *, include_formulas: bool = False, legacy_office: bool = False, msg_depth: int = 0) -> tuple[str, str]:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        raw = path.read_bytes()
        text, _ = decode_bytes(raw)
        return normalize_text(text), 'OK'
    if ext in WORD_EXTS:
        return extract_word(path), 'OK'
    if ext in EXCEL_EXTS:
        return extract_excel(path, include_formulas=include_formulas), 'OK'
    if ext in PPT_EXTS:
        return extract_powerpoint(path), 'OK'
    if ext in PDF_EXTS:
        return extract_pdf(path)
    if ext in RTF_EXTS:
        return extract_rtf(path), 'OK'
    if ext in MSG_EXTS:
        return extract_msg(path, depth=msg_depth), 'OK'
    if ext in LEGACY_OFFICE_EXTS:
        if not legacy_office:
            return '', 'LEGACY_OFFICE_SKIPPED'
        with tempfile.TemporaryDirectory(prefix='pstx_legacy_') as td:
            converted = _convert_legacy(path, Path(td))
            return extract_attachment_path(converted, include_formulas=include_formulas, legacy_office=False, msg_depth=msg_depth)
    return '', 'UNSUPPORTED'
