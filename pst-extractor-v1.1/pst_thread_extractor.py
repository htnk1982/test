from __future__ import annotations

import base64
import concurrent.futures as cf
import datetime as dt
import email
from email import policy
from email.parser import Parser
from email.utils import getaddresses
import hashlib
import json
import os
import queue
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import traceback
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from attachment_text import SUPPORTED_EXTS, extract_attachment_path, html_to_text, normalize_text

APP_NAME = 'PST Thread Extractor'
APP_VERSION = '1.1.0'
SCHEMA_VERSION = '2'

MAILISH_PREFIXES = ('IPM.Note', 'REPORT.IPM.Note', 'IPM.Schedule.Meeting')
EMAIL_RE = re.compile(r'(?i)(?<![\w.+-])([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})(?![\w.-])')
MSGID_RE = re.compile(r'<[^<>\s]+>')

# MAPI property IDs used by libpff
P_MESSAGE_CLASS = 0x001A
P_CONVERSATION_TOPIC = 0x0070
P_CONVERSATION_INDEX = 0x0071
P_TRANSPORT_HEADERS = 0x007D
P_RECIPIENT_TYPE = 0x0C15
P_SENDER_EMAIL = 0x0C1F
P_DISPLAY_BCC = 0x0E02
P_DISPLAY_CC = 0x0E03
P_DISPLAY_TO = 0x0E04
P_EMAIL_ADDRESS = 0x3003
P_SMTP_ADDRESS = 0x39FE
P_SENDER_SMTP = 0x5D01
P_SENT_REPRESENTING_SMTP = 0x5D02
P_RECIPIENT_DISPLAY_NAME = 0x5FF6
P_DISPLAY_NAME = 0x3001
P_ATTACHMENT_FILENAME_SHORT = 0x3704
P_ATTACHMENT_FILENAME_LONG = 0x3707

RECIP_TO = 1
RECIP_CC = 2
RECIP_BCC = 3


@dataclass
class ExtractConfig:
    pst_path: str
    output_path: str
    emails: list[str]
    match_from: bool = True
    match_to: bool = True
    match_cc: bool = True
    match_bcc: bool = True
    extract_attachments: bool = True
    strip_quoted_history: bool = True
    dedupe_messages: bool = True
    dedupe_attachments: bool = True
    include_excel_formulas: bool = False
    legacy_office_attachments: bool = False
    skip_errors: bool = True
    keep_work_db: bool = False
    backend: str = 'auto'  # auto | libpff | outlook
    attachment_workers: int = 8
    max_attachment_mb: int = 250
    commit_every: int = 200

    def normalized(self) -> 'ExtractConfig':
        emails = []
        seen = set()
        for value in self.emails[:3]:
            v = normalize_email(value)
            if v and v not in seen:
                emails.append(v)
                seen.add(v)
        c = ExtractConfig(**asdict(self))
        c.emails = emails
        c.attachment_workers = max(1, min(int(c.attachment_workers), 16))
        c.max_attachment_mb = max(1, int(c.max_attachment_mb))
        c.commit_every = max(20, int(c.commit_every))
        return c


@dataclass
class MailMeta:
    message_key: str
    folder_path: str
    folder_index: int
    backend_locator: str
    item_identifier: str
    message_class: str
    subject: str
    normalized_subject: str
    conversation_topic: str
    conversation_root: str
    conversation_index_hex: str
    sent_iso: str
    sender_name: str
    from_addresses: list[str]
    to_addresses: list[str]
    cc_addresses: list[str]
    bcc_addresses: list[str]
    internet_message_id: str
    in_reply_to: str
    references: list[str]
    body: str
    attachment_count: int


class Cancelled(Exception):
    pass


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def normalize_email(value: str) -> str:
    value = (value or '').strip().strip('<>').lower()
    if not value:
        return ''
    m = EMAIL_RE.search(value)
    return m.group(1).lower() if m else (value if '@' in value else '')


def unique_emails(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for value in values:
        v = normalize_email(value)
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def emails_from_header(value: str) -> list[str]:
    if not value:
        return []
    parsed = [addr for _, addr in getaddresses([value]) if addr]
    parsed += EMAIL_RE.findall(value)
    return unique_emails(parsed)


def safe_str(value: Any) -> str:
    if value is None:
        return ''
    try:
        return str(value)
    except Exception:
        return ''


def safe_datetime(value: Any) -> str:
    if not value:
        return ''
    try:
        if isinstance(value, dt.datetime):
            return value.isoformat(sep=' ', timespec='seconds')
        return safe_str(value)
    except Exception:
        return safe_str(value)


def normalize_subject(subject: str) -> str:
    s = normalize_text(subject or '').strip()
    # Repeated reply/forward prefixes, including common Japanese forms.
    pat = re.compile(r'^\s*(?:(?:re|fw|fwd)\s*:\s*|返信\s*[:：]\s*|転送\s*[:：]\s*)', re.I)
    while True:
        n = pat.sub('', s, count=1)
        if n == s:
            break
        s = n.strip()
    return re.sub(r'\s+', ' ', s).casefold()


def parse_transport_headers(raw: str) -> dict[str, Any]:
    out = {'from': [], 'to': [], 'cc': [], 'bcc': [], 'message_id': '', 'in_reply_to': '', 'references': []}
    if not raw:
        return out
    try:
        msg = Parser(policy=policy.default).parsestr(raw, headersonly=True)
        out['from'] = emails_from_header(safe_str(msg.get('From', '')))
        out['to'] = emails_from_header(safe_str(msg.get('To', '')))
        out['cc'] = emails_from_header(safe_str(msg.get('Cc', '')))
        out['bcc'] = emails_from_header(safe_str(msg.get('Bcc', '')))
        out['message_id'] = canonical_msgid(safe_str(msg.get('Message-ID', '')))
        out['in_reply_to'] = canonical_msgid(safe_str(msg.get('In-Reply-To', '')))
        refs = []
        for h in msg.get_all('References', []):
            refs.extend(MSGID_RE.findall(safe_str(h)))
        out['references'] = [canonical_msgid(x) for x in refs if canonical_msgid(x)]
    except Exception:
        # Conservative regex fallback.
        for name in ('from', 'to', 'cc', 'bcc'):
            m = re.search(rf'(?im)^{name}\s*:\s*(.+(?:\n[ \t].+)*)', raw)
            if m:
                out[name] = emails_from_header(m.group(1).replace('\n', ' '))
        mid = re.search(r'(?im)^message-id\s*:\s*(<[^>]+>)', raw)
        if mid:
            out['message_id'] = canonical_msgid(mid.group(1))
    return out


def canonical_msgid(value: str) -> str:
    if not value:
        return ''
    m = MSGID_RE.search(value)
    return (m.group(0) if m else value.strip()).lower()


def strip_reply_history(text: str) -> str:
    """Best-effort removal of quoted prior messages to reduce archive size.

    The operation is intentionally conservative: it trims only strongly recognizable
    Outlook/Gmail reply separators and quote-only lines. It does not remove signatures.
    """
    text = normalize_text(text)
    if not text:
        return ''
    lines = text.split('\n')
    cut = len(lines)
    hard_markers = [
        re.compile(r'^\s*-{2,}\s*Original Message\s*-{2,}\s*$', re.I),
        re.compile(r'^\s*-{2,}\s*元のメッセージ\s*-{2,}\s*$'),
        re.compile(r'^\s*On\s+.+\s+wrote:\s*$', re.I),
    ]
    jp_hdr = re.compile(r'^\s*(差出人|送信日時|宛先|ＣＣ|CC|件名)\s*[:：]', re.I)
    en_hdr = re.compile(r'^\s*(From|Sent|Date|To|Cc|Subject)\s*:', re.I)
    for i, line in enumerate(lines):
        if any(p.match(line) for p in hard_markers):
            cut = i
            break
        # Outlook header block: require at least 3 recognizable header fields nearby.
        if jp_hdr.match(line) or en_hdr.match(line):
            window = lines[i:i+7]
            hits = sum(1 for x in window if jp_hdr.match(x) or en_hdr.match(x))
            if hits >= 3:
                cut = i
                break
    lines = lines[:cut]
    # Remove contiguous quote-only lines left by some clients.
    filtered = [line for line in lines if not re.match(r'^\s*>', line)]
    return normalize_text('\n'.join(filtered))


def compress_text(text: str) -> bytes:
    return zlib.compress((text or '').encode('utf-8'), level=6)


def decompress_text(blob: Optional[bytes]) -> str:
    if not blob:
        return ''
    return zlib.decompress(blob).decode('utf-8', errors='replace')


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def config_fingerprint(cfg: ExtractConfig) -> str:
    p = Path(cfg.pst_path)
    st = p.stat()
    material = {
        'schema': SCHEMA_VERSION,
        'pst_path': str(p.resolve()),
        'pst_size': st.st_size,
        'pst_mtime_ns': st.st_mtime_ns,
        'emails': sorted(cfg.emails),
        'fields': [cfg.match_from, cfg.match_to, cfg.match_cc, cfg.match_bcc],
        'attachments': cfg.extract_attachments,
        'strip_quoted': cfg.strip_quoted_history,
        'dedupe_messages': cfg.dedupe_messages,
        'dedupe_attachments': cfg.dedupe_attachments,
        'excel_formulas': cfg.include_excel_formulas,
        'legacy_office': cfg.legacy_office_attachments,
        'backend': cfg.backend,
        'max_attachment_mb': cfg.max_attachment_mb,
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class WorkDB:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(str(path), timeout=60)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self.conn.execute('PRAGMA temp_store=MEMORY')
        self.conn.execute('PRAGMA cache_size=-65536')  # ~64 MiB
        self._create()

    def _create(self):
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS folders(
            backend TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            last_index INTEGER NOT NULL DEFAULT -1,
            total_count INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(backend, folder_path)
        );
        CREATE TABLE IF NOT EXISTS messages(
            message_key TEXT PRIMARY KEY,
            folder_path TEXT NOT NULL,
            folder_index INTEGER NOT NULL,
            backend_locator TEXT NOT NULL,
            item_identifier TEXT,
            message_class TEXT,
            subject TEXT,
            normalized_subject TEXT,
            conversation_topic TEXT,
            conversation_root TEXT,
            conversation_index_hex TEXT,
            sent_iso TEXT,
            sender_name TEXT,
            from_json TEXT,
            to_json TEXT,
            cc_json TEXT,
            bcc_json TEXT,
            internet_message_id TEXT,
            in_reply_to TEXT,
            references_json TEXT,
            body_z BLOB,
            body_hash TEXT,
            dedupe_key TEXT,
            duplicate_of TEXT,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            attachment_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_messages_thread ON messages(conversation_root, normalized_subject);
        CREATE INDEX IF NOT EXISTS ix_messages_msgid ON messages(internet_message_id);
        CREATE INDEX IF NOT EXISTS ix_messages_dedupe ON messages(dedupe_key);
        CREATE TABLE IF NOT EXISTS attachments(
            attachment_key TEXT PRIMARY KEY,
            message_key TEXT NOT NULL,
            attachment_index INTEGER NOT NULL,
            filename TEXT,
            size_bytes INTEGER,
            status TEXT NOT NULL DEFAULT 'PENDING',
            text_hash TEXT,
            error TEXT,
            UNIQUE(message_key, attachment_index)
        );
        CREATE INDEX IF NOT EXISTS ix_attachments_status ON attachments(status);
        CREATE TABLE IF NOT EXISTS attachment_texts(
            text_hash TEXT PRIMARY KEY,
            text_z BLOB NOT NULL,
            char_count INTEGER NOT NULL,
            source_attachment_key TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS errors(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phase TEXT,
            locator TEXT,
            error TEXT,
            ts TEXT
        );
        CREATE TABLE IF NOT EXISTS partial_written(
            kind TEXT NOT NULL,
            object_key TEXT NOT NULL,
            written_ts TEXT NOT NULL,
            PRIMARY KEY(kind, object_key)
        );
        ''')
        self.conn.commit()

    def close(self):
        self.conn.commit(); self.conn.close()

    def set_meta(self, key: str, value: str):
        self.conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)', (key, value))

    def get_meta(self, key: str, default: str = '') -> str:
        row = self.conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def folder_state(self, backend: str, folder_path: str) -> tuple[int, int, int]:
        row = self.conn.execute('SELECT last_index,total_count,completed FROM folders WHERE backend=? AND folder_path=?', (backend, folder_path)).fetchone()
        return tuple(row) if row else (-1, 0, 0)

    def update_folder(self, backend: str, folder_path: str, last_index: int, total_count: int, completed: int):
        self.conn.execute('''INSERT INTO folders(backend,folder_path,last_index,total_count,completed)
            VALUES(?,?,?,?,?) ON CONFLICT(backend,folder_path) DO UPDATE SET
            last_index=excluded.last_index,total_count=excluded.total_count,completed=excluded.completed''',
            (backend, folder_path, last_index, total_count, completed))

    def add_error(self, phase: str, locator: str, exc: Any):
        txt = f'{type(exc).__name__}: {exc}' if isinstance(exc, BaseException) else safe_str(exc)
        self.conn.execute('INSERT INTO errors(phase,locator,error,ts) VALUES(?,?,?,?)', (phase, locator, txt[:8000], now_iso()))

    def find_duplicate(self, dedupe_key: str) -> str:
        if not dedupe_key:
            return ''
        row = self.conn.execute("SELECT message_key FROM messages WHERE dedupe_key=? AND (duplicate_of IS NULL OR duplicate_of='') LIMIT 1", (dedupe_key,)).fetchone()
        return row[0] if row else ''

    def insert_message(self, m: MailMeta, dedupe_key: str, duplicate_of: str):
        self.conn.execute('''INSERT OR REPLACE INTO messages(
            message_key,folder_path,folder_index,backend_locator,item_identifier,message_class,subject,normalized_subject,
            conversation_topic,conversation_root,conversation_index_hex,sent_iso,sender_name,from_json,to_json,cc_json,bcc_json,
            internet_message_id,in_reply_to,references_json,body_z,body_hash,dedupe_key,duplicate_of,attachment_count)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            m.message_key,m.folder_path,m.folder_index,m.backend_locator,m.item_identifier,m.message_class,m.subject,m.normalized_subject,
            m.conversation_topic,m.conversation_root,m.conversation_index_hex,m.sent_iso,m.sender_name,
            json.dumps(m.from_addresses,ensure_ascii=False),json.dumps(m.to_addresses,ensure_ascii=False),
            json.dumps(m.cc_addresses,ensure_ascii=False),json.dumps(m.bcc_addresses,ensure_ascii=False),
            m.internet_message_id,m.in_reply_to,json.dumps(m.references,ensure_ascii=False),
            compress_text(m.body),sha256_text(m.body),dedupe_key,duplicate_of,m.attachment_count))
        if duplicate_of:
            self.conn.execute('UPDATE messages SET duplicate_count=duplicate_count+1 WHERE message_key=?', (duplicate_of,))

    def insert_attachment(self, message_key: str, idx: int, filename: str, size_bytes: int):
        key = f'{message_key}:A{idx:04d}'
        self.conn.execute('''INSERT OR IGNORE INTO attachments(attachment_key,message_key,attachment_index,filename,size_bytes,status)
                           VALUES(?,?,?,?,?,'PENDING')''', (key, message_key, idx, filename, size_bytes))

    def pending_attachments(self) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        rows = self.conn.execute('''SELECT a.*,m.backend_locator,m.folder_path,m.folder_index
                                  FROM attachments a JOIN messages m ON m.message_key=a.message_key
                                  WHERE a.status='PENDING' AND (m.duplicate_of IS NULL OR m.duplicate_of='')
                                  ORDER BY m.folder_path,m.folder_index,a.attachment_index''').fetchall()
        self.conn.row_factory = None
        return rows

    def set_attachment_result(self, key: str, status: str, text: str = '', error: str = '', dedupe: bool = True):
        text_hash = ''
        if text:
            text_hash = sha256_text(text) if dedupe else sha256_text(key + '\n' + text)
            row = self.conn.execute('SELECT text_hash FROM attachment_texts WHERE text_hash=?', (text_hash,)).fetchone()
            if row is None:
                self.conn.execute('INSERT INTO attachment_texts(text_hash,text_z,char_count,source_attachment_key) VALUES(?,?,?,?)',
                                  (text_hash, compress_text(text), len(text), key))
        self.conn.execute('UPDATE attachments SET status=?,text_hash=?,error=? WHERE attachment_key=?', (status, text_hash, error[:8000], key))

    def counts(self) -> dict[str, int]:
        q = self.conn.execute
        return {
            'messages': q("SELECT COUNT(*) FROM messages WHERE duplicate_of IS NULL OR duplicate_of='' ").fetchone()[0],
            'duplicates': q("SELECT COUNT(*) FROM messages WHERE duplicate_of IS NOT NULL AND duplicate_of<>''").fetchone()[0],
            'attachments': q('SELECT COUNT(*) FROM attachments').fetchone()[0],
            'attachments_done': q("SELECT COUNT(*) FROM attachments WHERE status<>'PENDING'").fetchone()[0],
            'errors': q('SELECT COUNT(*) FROM errors').fetchone()[0],
        }


    def partial_is_written(self, kind: str, object_key: str) -> bool:
        return self.conn.execute('SELECT 1 FROM partial_written WHERE kind=? AND object_key=?', (kind, object_key)).fetchone() is not None

    def mark_partial_written(self, kind: str, object_key: str):
        self.conn.execute('INSERT OR IGNORE INTO partial_written(kind,object_key,written_ts) VALUES(?,?,?)',
                          (kind, object_key, now_iso()))

    def reset_partial_written(self):
        self.conn.execute('DELETE FROM partial_written')
        self.conn.commit()


class BaseBackend:
    name = 'base'
    def __init__(self, pst_path: Path): self.pst_path = pst_path
    def open(self): raise NotImplementedError
    def close(self): pass
    def folders(self): raise NotImplementedError
    def count_messages(self, folder) -> int: raise NotImplementedError
    def get_message(self, folder, index: int): raise NotImplementedError
    def folder_path(self, folder) -> str: raise NotImplementedError
    def message_meta(self, folder, index: int, msg, cfg: ExtractConfig) -> Optional[MailMeta]: raise NotImplementedError
    def attachment_meta(self, msg) -> list[tuple[int,str,int]]: return []
    def write_attachment_to(self, locator: str, attachment_index: int, out_path: Path): raise NotImplementedError


class LibpffBackend(BaseBackend):
    name = 'libpff'
    def open(self):
        try:
            import pypff  # type: ignore
        except Exception as e:
            raise RuntimeError('高速モードには libpff-python-windows (import名: pypff) が必要です。Python 3.13版でのビルドを推奨します。') from e
        self.pypff = pypff
        self.file = pypff.file()
        self.file.open(str(self.pst_path))
        self.root = self.file.get_root_folder()
        self._folder_cache: dict[str, Any] = {}

    def close(self):
        try: self.file.close()
        except Exception: pass

    def _walk(self, folder, parent: str = ''):
        name = safe_str(getattr(folder, 'name', '') or getattr(folder, 'get_name', lambda: '')()) or '(root)'
        path = f'{parent}/{name}' if parent else f'/{name}'
        self._folder_cache[path] = folder
        yield folder, path
        try: n = int(folder.number_of_sub_folders)
        except Exception:
            try: n = int(folder.get_number_of_sub_folders())
            except Exception: n = 0
        for i in range(n):
            try: child = folder.get_sub_folder(i)
            except Exception: continue
            yield from self._walk(child, path)

    def folders(self):
        yield from self._walk(self.root)

    def count_messages(self, folder) -> int:
        try: return int(folder.number_of_sub_messages)
        except Exception: return int(folder.get_number_of_sub_messages())

    def get_message(self, folder, index: int):
        return folder.get_sub_message(index)

    def folder_path(self, folder) -> str:
        for p, f in self._folder_cache.items():
            if f is folder: return p
        return '/(unknown)'

    @staticmethod
    def _record_sets(item):
        try:
            n = int(item.number_of_record_sets)
        except Exception:
            try: n = int(item.get_number_of_record_sets())
            except Exception: return []
        out = []
        for i in range(n):
            try: out.append(item.get_record_set(i))
            except Exception: pass
        return out

    @classmethod
    def _entry(cls, item, propid: int):
        for rs in cls._record_sets(item):
            try:
                e = rs.get_entry_by_type(propid)
                if e is not None:
                    return e
            except Exception:
                pass
        return None

    @classmethod
    def _str_prop(cls, item, propids: Iterable[int]) -> str:
        for pid in propids:
            e = cls._entry(item, pid)
            if e is not None:
                try:
                    v = e.get_data_as_string()
                    if v:
                        return safe_str(v).strip()
                except Exception:
                    pass
        return ''

    @classmethod
    def _int_prop(cls, item, propid: int) -> Optional[int]:
        e = cls._entry(item, propid)
        if e is None: return None
        try: return int(e.get_data_as_integer())
        except Exception: return None

    @classmethod
    def _recipient_rows(cls, msg) -> dict[str, list[str]]:
        out = {'to': [], 'cc': [], 'bcc': []}
        try: recips = msg.recipients
        except Exception:
            try: recips = msg.get_recipients()
            except Exception: recips = None
        if recips is None:
            return out
        for rs in cls._record_sets(recips):
            rtype = None
            for pid in (P_RECIPIENT_TYPE,):
                try:
                    e = rs.get_entry_by_type(pid)
                    if e is not None:
                        rtype = int(e.get_data_as_integer())
                        break
                except Exception:
                    pass
            addr = ''
            for pid in (P_SMTP_ADDRESS, P_EMAIL_ADDRESS):
                try:
                    e = rs.get_entry_by_type(pid)
                    if e is not None:
                        v = safe_str(e.get_data_as_string()).strip()
                        if '@' in v:
                            addr = normalize_email(v); break
                except Exception:
                    pass
            if not addr:
                continue
            if rtype == RECIP_TO: out['to'].append(addr)
            elif rtype == RECIP_CC: out['cc'].append(addr)
            elif rtype == RECIP_BCC: out['bcc'].append(addr)
        for k in out: out[k] = unique_emails(out[k])
        return out

    @classmethod
    def _message_class(cls, msg) -> str:
        return cls._str_prop(msg, [P_MESSAGE_CLASS])

    @staticmethod
    def _conv_bytes(msg) -> bytes:
        try:
            v = msg.conversation_index
        except Exception:
            try: v = msg.get_conversation_index()
            except Exception: v = None
        return bytes(v) if isinstance(v, (bytes, bytearray)) else b''

    @staticmethod
    def _conv_root(ci: bytes, topic: str) -> str:
        # MS-OXOMSG: 22-byte header = 6-byte prefix/time + 16-byte ConversationID.
        if len(ci) >= 22 and ci[0] == 0x01:
            return 'CID:' + ci[6:22].hex()
        norm = normalize_subject(topic)
        return 'TOPIC:' + hashlib.sha1(norm.encode('utf-8')).hexdigest() if norm else ''

    def message_meta(self, folder, index: int, msg, cfg: ExtractConfig) -> Optional[MailMeta]:
        mclass = self._message_class(msg)
        # Libpff folder sub_messages can include calendar/contact-like items.
        if mclass and not mclass.upper().startswith(tuple(x.upper() for x in MAILISH_PREFIXES)):
            return None
        # Hot path: resolve sender/recipient rows first. The transport-header
        # property can be large, so do not fetch it for clearly irrelevant mail.
        sender = self._str_prop(msg, [P_SENDER_SMTP, P_SENT_REPRESENTING_SMTP, P_SENDER_EMAIL])
        from_addrs = unique_emails([sender] if sender else [])
        rec = self._recipient_rows(msg)
        to_addrs = rec['to']; cc_addrs = rec['cc']; bcc_addrs = rec['bcc']
        if not matches_filter(cfg, from_addrs, to_addrs, cc_addrs, bcc_addrs):
            return None
        try: headers_raw = safe_str(msg.transport_headers)
        except Exception:
            try: headers_raw = safe_str(msg.get_transport_headers())
            except Exception: headers_raw = ''
        h = parse_transport_headers(headers_raw)
        from_addrs = unique_emails(from_addrs + h['from'])
        to_addrs = unique_emails(to_addrs + h['to'])
        cc_addrs = unique_emails(cc_addrs + h['cc'])
        bcc_addrs = unique_emails(bcc_addrs + h['bcc'])
        try: subject = safe_str(msg.subject)
        except Exception:
            try: subject = safe_str(msg.get_subject())
            except Exception: subject = ''
        try: topic = safe_str(msg.conversation_topic)
        except Exception:
            topic = self._str_prop(msg, [P_CONVERSATION_TOPIC]) or subject
        ci = self._conv_bytes(msg)
        body = ''
        try: body = safe_str(msg.plain_text_body)
        except Exception:
            try: body = safe_str(msg.get_plain_text_body())
            except Exception: pass
        if not body:
            try: hb = msg.html_body
            except Exception:
                try: hb = msg.get_html_body()
                except Exception: hb = ''
            if isinstance(hb, bytes):
                try: hb = hb.decode('utf-8', errors='replace')
                except Exception: hb = ''
            if hb: body = html_to_text(safe_str(hb))
        if not body:
            try:
                rb = safe_str(msg.rtf_body)
                if rb:
                    try:
                        from striprtf.striprtf import rtf_to_text  # type: ignore
                        body = rtf_to_text(rb)
                    except Exception:
                        body = rb
            except Exception: pass
        body = normalize_text(body)
        if cfg.strip_quoted_history:
            body = strip_reply_history(body)
        try: sent = msg.client_submit_time or msg.delivery_time or msg.creation_time
        except Exception: sent = None
        try: sender_name = safe_str(msg.sender_name)
        except Exception: sender_name = ''
        try: itemid = safe_str(msg.identifier)
        except Exception:
            try: itemid = safe_str(msg.get_identifier())
            except Exception: itemid = f'idx-{index}'
        fpath = self.folder_path(folder)
        message_key = f'PFF:{fpath}:{itemid}:{index}'
        try: acount = int(msg.number_of_attachments)
        except Exception:
            try: acount = int(msg.get_number_of_attachments())
            except Exception: acount = 0
        locator = json.dumps({'folder_path': fpath, 'message_index': index}, ensure_ascii=False)
        return MailMeta(
            message_key=message_key, folder_path=fpath, folder_index=index, backend_locator=locator,
            item_identifier=itemid, message_class=mclass, subject=subject, normalized_subject=normalize_subject(subject),
            conversation_topic=topic, conversation_root=self._conv_root(ci, topic or subject), conversation_index_hex=ci.hex(),
            sent_iso=safe_datetime(sent), sender_name=sender_name, from_addresses=from_addrs,
            to_addresses=to_addrs, cc_addresses=cc_addrs, bcc_addresses=bcc_addrs,
            internet_message_id=h['message_id'], in_reply_to=h['in_reply_to'], references=h['references'],
            body=body, attachment_count=acount)

    def attachment_meta(self, msg) -> list[tuple[int,str,int]]:
        try: n = int(msg.number_of_attachments)
        except Exception:
            try: n = int(msg.get_number_of_attachments())
            except Exception: n = 0
        out = []
        for i in range(n):
            try:
                att = msg.get_attachment(i)
                name = safe_str(getattr(att, 'long_filename', '') or '') or self._str_prop(att, [P_ATTACHMENT_FILENAME_LONG, P_ATTACHMENT_FILENAME_SHORT]) or f'attachment_{i+1}'
                try: size = int(att.size)
                except Exception:
                    try: size = int(att.get_size())
                    except Exception: size = 0
                out.append((i, Path(name).name or f'attachment_{i+1}', size))
            except Exception:
                out.append((i, f'attachment_{i+1}', 0))
        return out

    def _folder_by_path(self, target: str):
        if target in self._folder_cache:
            return self._folder_cache[target]
        for folder, path in self.folders():
            if path == target:
                return folder
        raise KeyError(target)

    def write_attachment_to(self, locator: str, attachment_index: int, out_path: Path):
        loc = json.loads(locator)
        folder = self._folder_by_path(loc['folder_path'])
        msg = folder.get_sub_message(int(loc['message_index']))
        att = msg.get_attachment(int(attachment_index))
        try: att.seek_offset(0, 0)
        except Exception: pass
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open('wb') as f:
            while True:
                chunk = att.read_buffer(4 * 1024 * 1024)
                if not chunk: break
                f.write(chunk)


class OutlookBackend(BaseBackend):
    name = 'outlook'
    def open(self):
        if os.name != 'nt':
            raise RuntimeError('Outlook互換モードはWindows専用です。')
        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore
        except Exception as e:
            raise RuntimeError('Outlook互換モードには pywin32 が必要です。') from e
        self.pythoncom = pythoncom; self.win32 = win32com.client
        pythoncom.CoInitialize()
        self.app = self.win32.Dispatch('Outlook.Application')
        self.ns = self.app.GetNamespace('MAPI')
        target = os.path.normcase(os.path.abspath(str(self.pst_path)))
        self.store = None; self.added_store = False
        for i in range(1, self.ns.Stores.Count + 1):
            try:
                s = self.ns.Stores.Item(i)
                fp = safe_str(s.FilePath)
                if fp and os.path.normcase(os.path.abspath(fp)) == target:
                    self.store = s; break
            except Exception: pass
        if self.store is None:
            self.ns.AddStore(str(self.pst_path))
            self.added_store = True
            for i in range(1, self.ns.Stores.Count + 1):
                try:
                    s = self.ns.Stores.Item(i)
                    fp = safe_str(s.FilePath)
                    if fp and os.path.normcase(os.path.abspath(fp)) == target:
                        self.store = s; break
                except Exception: pass
        if self.store is None:
            raise RuntimeError('PSTをOutlookプロファイルへ接続できませんでした。')
        self.root = self.store.GetRootFolder()
        self.store_id = safe_str(self.root.StoreID)
        self._folder_paths = {}

    def close(self):
        try:
            if getattr(self, 'added_store', False): self.ns.RemoveStore(self.root)
        except Exception: pass
        try: self.pythoncom.CoUninitialize()
        except Exception: pass

    def _walk(self, folder, parent=''):
        name = safe_str(folder.Name) or '(root)'
        path = f'{parent}/{name}' if parent else f'/{name}'
        self._folder_paths[id(folder)] = path
        yield folder, path
        try: n = int(folder.Folders.Count)
        except Exception: n = 0
        for i in range(1, n+1):
            try: child = folder.Folders.Item(i)
            except Exception: continue
            yield from self._walk(child, path)

    def folders(self): yield from self._walk(self.root)
    def folder_path(self, folder): return self._folder_paths.get(id(folder), safe_str(getattr(folder,'FolderPath','')) or '/(unknown)')
    def count_messages(self, folder):
        try: return int(folder.Items.Count)
        except Exception: return 0
    def get_message(self, folder, index: int): return folder.Items.Item(index + 1)

    @staticmethod
    def _pa(item, dasl: str) -> str:
        try: return safe_str(item.PropertyAccessor.GetProperty(dasl)).strip()
        except Exception: return ''

    def _smtp_from_address_entry(self, ae) -> str:
        if ae is None: return ''
        try:
            t = safe_str(ae.Type).upper()
            if t == 'EX':
                try:
                    eu = ae.GetExchangeUser()
                    if eu:
                        v = normalize_email(safe_str(eu.PrimarySmtpAddress))
                        if v: return v
                except Exception: pass
                try:
                    dl = ae.GetExchangeDistributionList()
                    if dl:
                        v = normalize_email(safe_str(dl.PrimarySmtpAddress))
                        if v: return v
                except Exception: pass
            v = normalize_email(self._pa(ae, 'http://schemas.microsoft.com/mapi/proptag/0x39FE001F'))
            if v: return v
            return normalize_email(safe_str(ae.Address))
        except Exception: return ''

    def _sender(self, item) -> list[str]:
        v = normalize_email(self._pa(item, 'http://schemas.microsoft.com/mapi/proptag/0x5D01001F'))
        if v: return [v]
        try:
            if safe_str(item.SenderEmailType).upper() == 'EX':
                v = self._smtp_from_address_entry(item.Sender)
            else: v = normalize_email(safe_str(item.SenderEmailAddress))
            return [v] if v else []
        except Exception: return []

    def _recipients(self, item) -> dict[str,list[str]]:
        out = {'to': [], 'cc': [], 'bcc': []}
        try: recips = item.Recipients; n = recips.Count
        except Exception: return out
        for i in range(1, n+1):
            try:
                r = recips.Item(i); typ = int(r.Type)
                addr = self._smtp_from_address_entry(r.AddressEntry)
                if not addr: addr = normalize_email(safe_str(r.Address))
                if not addr: continue
                if typ == 1: out['to'].append(addr)
                elif typ == 2: out['cc'].append(addr)
                elif typ == 3: out['bcc'].append(addr)
            except Exception: pass
        for k in out: out[k] = unique_emails(out[k])
        return out

    def message_meta(self, folder, index: int, item, cfg: ExtractConfig) -> Optional[MailMeta]:
        try: mclass = safe_str(item.MessageClass)
        except Exception: mclass = ''
        if mclass and not mclass.upper().startswith(tuple(x.upper() for x in MAILISH_PREFIXES)):
            return None
        from_addrs = self._sender(item); rec = self._recipients(item)
        to_addrs, cc_addrs, bcc_addrs = rec['to'], rec['cc'], rec['bcc']
        if not matches_filter(cfg, from_addrs, to_addrs, cc_addrs, bcc_addrs): return None
        headers_raw = self._pa(item, 'http://schemas.microsoft.com/mapi/proptag/0x007D001F')
        h = parse_transport_headers(headers_raw)
        from_addrs = unique_emails(from_addrs + h['from'])
        to_addrs = unique_emails(to_addrs + h['to']); cc_addrs = unique_emails(cc_addrs + h['cc']); bcc_addrs = unique_emails(bcc_addrs + h['bcc'])
        subject = safe_str(getattr(item, 'Subject', ''))
        topic = safe_str(getattr(item, 'ConversationTopic', '')) or subject
        try: conv_id = safe_str(item.ConversationID)
        except Exception: conv_id = ''
        try: conv_index = safe_str(item.ConversationIndex)
        except Exception: conv_index = ''
        body = normalize_text(safe_str(getattr(item, 'Body', '')))
        if cfg.strip_quoted_history: body = strip_reply_history(body)
        sent = ''
        for attr in ('SentOn','ReceivedTime','CreationTime'):
            try:
                v = getattr(item, attr)
                if v: sent = safe_datetime(v); break
            except Exception: pass
        try: sender_name = safe_str(item.SenderName)
        except Exception: sender_name = ''
        try: entry_id = safe_str(item.EntryID)
        except Exception: entry_id = f'idx-{index}'
        fpath = self.folder_path(folder)
        key = f'OOM:{entry_id or fpath+":"+str(index)}'
        try: acount = int(item.Attachments.Count)
        except Exception: acount = 0
        root = ('CID:' + conv_id) if conv_id else ('TOPIC:' + hashlib.sha1(normalize_subject(topic).encode()).hexdigest() if topic else '')
        locator = json.dumps({'entry_id': entry_id, 'store_id': self.store_id}, ensure_ascii=False)
        return MailMeta(key,fpath,index,locator,entry_id,mclass,subject,normalize_subject(subject),topic,root,conv_index,sent,sender_name,
                        from_addrs,to_addrs,cc_addrs,bcc_addrs,h['message_id'],h['in_reply_to'],h['references'],body,acount)

    def attachment_meta(self, item) -> list[tuple[int,str,int]]:
        out=[]
        try: n=int(item.Attachments.Count)
        except Exception: return out
        for i in range(1,n+1):
            try:
                a=item.Attachments.Item(i); name=Path(safe_str(a.FileName) or f'attachment_{i}').name
                try:size=int(a.Size)
                except Exception:size=0
                out.append((i-1,name,size))
            except Exception: out.append((i-1,f'attachment_{i}',0))
        return out

    def write_attachment_to(self, locator: str, attachment_index: int, out_path: Path):
        loc=json.loads(locator); item=self.ns.GetItemFromID(loc['entry_id'],loc.get('store_id') or None)
        att=item.Attachments.Item(int(attachment_index)+1)
        out_path.parent.mkdir(parents=True,exist_ok=True); att.SaveAsFile(str(out_path))


def matches_filter(cfg: ExtractConfig, from_addrs: list[str], to_addrs: list[str], cc_addrs: list[str], bcc_addrs: list[str]) -> bool:
    if not cfg.emails:
        return True
    targets=set(cfg.emails)
    return ((cfg.match_from and bool(targets.intersection(from_addrs))) or
            (cfg.match_to and bool(targets.intersection(to_addrs))) or
            (cfg.match_cc and bool(targets.intersection(cc_addrs))) or
            (cfg.match_bcc and bool(targets.intersection(bcc_addrs))))


def make_backend(cfg: ExtractConfig, log) -> BaseBackend:
    if cfg.backend in ('auto','libpff'):
        try:
            import pypff  # type: ignore # noqa:F401
            log('Backend: libpff direct PST reader（高速）')
            return LibpffBackend(Path(cfg.pst_path))
        except Exception as e:
            if cfg.backend == 'libpff': raise
            log(f'libpff unavailable; Outlook互換モードへフォールバック: {e}')
    return OutlookBackend(Path(cfg.pst_path))


class Engine:
    def __init__(self, cfg: ExtractConfig, event_q: queue.Queue, cancel_event: threading.Event):
        self.cfg = cfg.normalized(); self.q = event_q; self.cancel = cancel_event
        self.output = Path(self.cfg.output_path)
        self.workdir = Path(str(self.output) + '.work')
        self.db_path = self.workdir / 'checkpoint.sqlite3'
        self.tempdir = self.workdir / 'attachments_tmp'
        self.partial_path = self.output.with_suffix('.partial.md')
        self.backend: Optional[BaseBackend] = None
        self.scanned = 0; self.matched = 0

    def emit(self, kind: str, **payload): self.q.put((kind,payload))
    def log(self, text: str): self.emit('log', text=text)
    def check_cancel(self):
        if self.cancel.is_set(): raise Cancelled()

    def _ensure_partial(self, db: WorkDB):
        if not self.partial_path.exists():
            db.reset_partial_written()
            self.partial_path.parent.mkdir(parents=True, exist_ok=True)
            with self.partial_path.open('w', encoding='utf-8', newline='\n') as f:
                f.write('# PST Extraction — PARTIAL OUTPUT\n\n')
                f.write('> 中断時の救済用ジャーナルです。スレッド再構成前の走査順で追記されます。最終成果物は別途生成される `.md` です。\n\n')
                f.write(f'- Source PST: `{Path(self.cfg.pst_path).name}`\n')
                f.write(f'- Started/Resumed: {now_iso()}\n\n---\n\n')

    def _sync_partial_messages(self, db: WorkDB, limit: int = 1000):
        self._ensure_partial(db)
        rows = db.conn.execute("""SELECT message_key,folder_path,subject,sent_iso,from_json,to_json,cc_json,bcc_json,body_z
                                  FROM messages
                                  WHERE (duplicate_of IS NULL OR duplicate_of='')
                                    AND message_key NOT IN (SELECT object_key FROM partial_written WHERE kind='message')
                                  ORDER BY rowid LIMIT ?""", (limit,)).fetchall()
        if not rows:
            return 0
        with self.partial_path.open('a', encoding='utf-8', newline='\n') as f:
            for key,folder,subject,sent,fr,to,cc,bcc,body_z in rows:
                f.write(f'## MESSAGE `{key}`\n\n')
                f.write(f'- Date: {sent or "(unknown)"}\n- Subject: {subject or "(no subject)"}\n')
                for label, raw in [('From',fr),('To',to),('Cc',cc),('Bcc',bcc)]:
                    try: vals=json.loads(raw or '[]')
                    except Exception: vals=[]
                    if vals: f.write(f'- {label}: {", ".join(vals)}\n')
                f.write(f'- PST folder: `{folder}`\n\n')
                body=decompress_text(body_z)
                f.write(body if body else '[NO TEXT BODY]')
                f.write('\n\n---\n\n')
                db.mark_partial_written('message', key)
        db.conn.commit()
        return len(rows)

    def _sync_partial_attachments(self, db: WorkDB, limit: int = 1000):
        self._ensure_partial(db)
        rows = db.conn.execute("""SELECT a.attachment_key,a.message_key,a.filename,a.status,a.text_hash,t.text_z
                                  FROM attachments a LEFT JOIN attachment_texts t ON t.text_hash=a.text_hash
                                  WHERE a.status<>'PENDING'
                                    AND a.attachment_key NOT IN (SELECT object_key FROM partial_written WHERE kind='attachment')
                                  ORDER BY a.rowid LIMIT ?""", (limit,)).fetchall()
        if not rows:
            return 0
        with self.partial_path.open('a', encoding='utf-8', newline='\n') as f:
            for key,mkey,filename,status,th,text_z in rows:
                f.write(f'## ATTACHMENT `{key}`\n\n- Parent message: `{mkey}`\n- Filename: `{filename or "(unnamed)"}`\n- Status: {status}\n\n')
                if text_z:
                    f.write(decompress_text(text_z))
                    f.write('\n')
                f.write('\n---\n\n')
                db.mark_partial_written('attachment', key)
        db.conn.commit()
        return len(rows)

    def run(self):
        self.workdir.mkdir(parents=True, exist_ok=True); self.tempdir.mkdir(parents=True, exist_ok=True)
        db = WorkDB(self.db_path)
        success = False
        try:
            self._ensure_partial(db)
            fp = config_fingerprint(self.cfg)
            old = db.get_meta('fingerprint')
            if old and old != fp:
                raise RuntimeError('再開DBの設定が今回のPST/抽出条件と一致しません。GUIで「新規開始」を選んでください。')
            if not old:
                db.set_meta('fingerprint',fp); db.set_meta('config',json.dumps(asdict(self.cfg),ensure_ascii=False)); db.set_meta('created',now_iso()); db.conn.commit()
            self.backend = make_backend(self.cfg, self.log); self.backend.open()
            db.set_meta('backend_used',self.backend.name); db.conn.commit()
            stage = db.get_meta('stage','scan')
            if stage == 'scan':
                self._scan(db)
                db.set_meta('stage','attachments'); db.conn.commit()
            self.check_cancel()
            if self.cfg.extract_attachments and db.get_meta('stage') == 'attachments':
                self._attachments(db)
            db.set_meta('stage','render'); db.conn.commit()
            self.check_cancel()
            self._render(db)
            db.set_meta('stage','done'); db.set_meta('completed',now_iso()); db.conn.commit()
            success = True
            counts=db.counts(); self.emit('done', output=str(self.output), counts=counts)
        except Cancelled:
            db.conn.commit()
            try:
                while self._sync_partial_messages(db): pass
                while self._sync_partial_attachments(db): pass
            except Exception: pass
            self.log(f'中止しました。チェックポイントと途中Markdownを保存しました: {self.partial_path}')
            self.emit('cancelled')
        except Exception as e:
            try:
                db.add_error('fatal','engine',e); db.conn.commit()
                while self._sync_partial_messages(db): pass
                while self._sync_partial_attachments(db): pass
            except Exception: pass
            self.emit('fatal', error=f'{type(e).__name__}: {e}', traceback=traceback.format_exc())
        finally:
            if self.backend:
                try: self.backend.close()
                except Exception: pass
            db.close()
            if success and self.output.exists():
                try: self.partial_path.unlink(missing_ok=True)
                except Exception: pass
                if not self.cfg.keep_work_db:
                    try: shutil.rmtree(self.workdir)
                    except Exception: pass

    def _scan(self, db: WorkDB):
        assert self.backend
        self.log('Phase 1/3: PSTを走査し、アドレス一致メールだけ本文抽出します。')
        # Counting is cheap compared with opening every message and makes progress meaningful.
        folder_rows = list(self.backend.folders())
        totals=[]; total_all=0
        for folder,path in folder_rows:
            try: n=self.backend.count_messages(folder)
            except Exception: n=0
            totals.append((folder,path,n)); total_all += n
        self.emit('phase', name='scan', total=total_all)
        commit_counter=0
        for folder,path,total in totals:
            self.check_cancel()
            last,_,completed = db.folder_state(self.backend.name,path)
            if completed:
                self.scanned += total; self.emit('progress', phase='scan', current=self.scanned,total=total_all,matched=self.matched); continue
            start=max(0,last+1)
            for idx in range(start,total):
                self.check_cancel(); locator=f'{path}#{idx}'
                try:
                    msg=self.backend.get_message(folder,idx)
                    meta=self.backend.message_meta(folder,idx,msg,self.cfg)
                    if meta is not None:
                        body_hash=sha256_text(meta.body)
                        dedupe_key=''
                        if self.cfg.dedupe_messages:
                            seed='|'.join([meta.internet_message_id,meta.sent_iso,','.join(meta.from_addresses),meta.subject,body_hash])
                            dedupe_key=hashlib.sha256(seed.encode('utf-8')).hexdigest()
                        dup=db.find_duplicate(dedupe_key) if dedupe_key else ''
                        db.insert_message(meta,dedupe_key,dup)
                        if not dup and self.cfg.extract_attachments:
                            for ai,name,size in self.backend.attachment_meta(msg): db.insert_attachment(meta.message_key,ai,name,size)
                        self.matched += 1
                    db.update_folder(self.backend.name,path,idx,total,0)
                except Exception as e:
                    db.add_error('scan',locator,e); db.update_folder(self.backend.name,path,idx,total,0)
                    if not self.cfg.skip_errors: raise
                self.scanned += 1; commit_counter += 1
                if commit_counter >= self.cfg.commit_every:
                    db.conn.commit(); commit_counter=0
                    self._sync_partial_messages(db, limit=max(1000, self.cfg.commit_every * 2))
                if self.scanned % 25 == 0:
                    self.emit('progress',phase='scan',current=self.scanned,total=total_all,matched=self.matched)
            db.update_folder(self.backend.name,path,total-1,total,1); db.conn.commit()
            self._sync_partial_messages(db, limit=5000)
        self.emit('progress',phase='scan',current=total_all,total=total_all,matched=self.matched)
        self.log(f'走査完了: {total_all:,}件走査 / {db.counts()["messages"]:,}件採用 / 重複{db.counts()["duplicates"]:,}件省略')

    def _attachments(self, db: WorkDB):
        assert self.backend
        pending=db.pending_attachments(); total=len(pending)
        self.log(f'Phase 2/3: 添付テキスト抽出 {total:,}件（最大 {self.cfg.attachment_workers} 並列）。')
        self.emit('phase',name='attachments',total=total)
        if not pending: return
        max_bytes=self.cfg.max_attachment_mb*1024*1024
        executor=cf.ThreadPoolExecutor(max_workers=self.cfg.attachment_workers,thread_name_prefix='att')
        in_flight: dict[cf.Future,tuple[str,Path]]={}
        done=0

        def collect_one(block: bool=False):
            nonlocal done
            if not in_flight: return
            done_set,_=cf.wait(list(in_flight),timeout=None if block else 0,return_when=cf.FIRST_COMPLETED)
            for fut in done_set:
                key,tmp=in_flight.pop(fut)
                try:
                    text,status=fut.result()
                    db.set_attachment_result(key,status,text,dedupe=self.cfg.dedupe_attachments)
                except Exception as e:
                    db.set_attachment_result(key,'ERROR','',f'{type(e).__name__}: {e}',dedupe=self.cfg.dedupe_attachments); db.add_error('attachment_extract',key,e)
                    if not self.cfg.skip_errors: raise
                finally:
                    try: tmp.unlink(missing_ok=True)
                    except Exception: pass
                done+=1
                if done%10==0:
                    db.conn.commit()
                    self._sync_partial_attachments(db, limit=500)
                self.emit('progress',phase='attachments',current=done,total=total,matched=self.matched)

        try:
            for row in pending:
                self.check_cancel()
                key=row['attachment_key']; filename=row['filename'] or f'attachment_{row["attachment_index"]+1}'
                suffix=Path(filename).suffix.lower()
                if suffix not in SUPPORTED_EXTS:
                    db.set_attachment_result(key,'UNSUPPORTED',dedupe=self.cfg.dedupe_attachments); done+=1; self.emit('progress',phase='attachments',current=done,total=total,matched=self.matched); continue
                if row['size_bytes'] and int(row['size_bytes'])>max_bytes:
                    db.set_attachment_result(key,'TOO_LARGE',dedupe=self.cfg.dedupe_attachments); done+=1; self.emit('progress',phase='attachments',current=done,total=total,matched=self.matched); continue
                safe_name=re.sub(r'[^A-Za-z0-9_.-]+','_',Path(filename).name)[:120] or f'att_{done}{suffix}'
                tmp=self.tempdir/f'{hashlib.sha1(key.encode()).hexdigest()}_{safe_name}'
                try:
                    self.backend.write_attachment_to(row['backend_locator'],int(row['attachment_index']),tmp)
                except Exception as e:
                    db.set_attachment_result(key,'ERROR','',f'{type(e).__name__}: {e}',dedupe=self.cfg.dedupe_attachments); db.add_error('attachment_read',key,e); done+=1
                    if not self.cfg.skip_errors: raise
                    continue
                fut=executor.submit(extract_attachment_path,tmp,include_formulas=self.cfg.include_excel_formulas,legacy_office=self.cfg.legacy_office_attachments)
                in_flight[fut]=(key,tmp)
                while len(in_flight)>=max(2,self.cfg.attachment_workers*2): collect_one(block=True)
                collect_one(block=False)
            while in_flight:
                self.check_cancel(); collect_one(block=True)
        finally:
            executor.shutdown(wait=True,cancel_futures=False); db.conn.commit()
            while self._sync_partial_attachments(db, limit=5000): pass
        self.log('添付テキスト抽出完了。')

    def _render(self, db: WorkDB):
        self.log('Phase 3/3: スレッドを時系列に並べ、単一Markdownを書き出します。')
        self.emit('phase',name='render',total=1)
        rows=db.conn.execute("""SELECT message_key,subject,normalized_subject,conversation_root,sent_iso,internet_message_id,in_reply_to,references_json,
                                     from_json,to_json,cc_json,bcc_json
                              FROM messages WHERE duplicate_of IS NULL OR duplicate_of='' ORDER BY sent_iso,message_key""").fetchall()
        n=len(rows)
        parent=list(range(n)); rank=[0]*n
        def find(x):
            while parent[x]!=x:
                parent[x]=parent[parent[x]]; x=parent[x]
            return x
        def union(a,b):
            ra,rb=find(a),find(b)
            if ra==rb:return
            if rank[ra]<rank[rb]: parent[ra]=rb
            elif rank[ra]>rank[rb]: parent[rb]=ra
            else: parent[rb]=ra; rank[ra]+=1
        by_conv={}; by_msgid={}
        for i,r in enumerate(rows):
            conv=r[3] or ''; mid=canonical_msgid(r[5] or '')
            if conv.startswith('CID:'):
                if conv in by_conv: union(i,by_conv[conv])
                else: by_conv[conv]=i
            if mid: by_msgid[mid]=i
        # RFC message linkage is the second-strongest signal.
        for i,r in enumerate(rows):
            refs=[]
            try: refs=json.loads(r[7] or '[]')
            except Exception: pass
            irt=canonical_msgid(r[6] or '')
            for ref in ([irt] if irt else [])+refs:
                ref=canonical_msgid(ref)
                if ref in by_msgid: union(i,by_msgid[ref])
        # Final fallback: same normalized topic + overlapping participant + reasonable time proximity.
        # This is used only where a strong ConversationID is absent.
        by_topic_last={}
        def participants(r):
            vals=[]
            for pos in (8,9,10,11):
                try: vals.extend(json.loads(r[pos] or '[]'))
                except Exception: pass
            return set(unique_emails(vals))
        def parsed_time(value):
            try: return dt.datetime.fromisoformat((value or '').replace('Z','+00:00'))
            except Exception: return None
        for i,r in enumerate(rows):
            conv=r[3] or ''; topic=r[2] or ''
            if conv.startswith('CID:') or not topic:
                continue
            prev=by_topic_last.get(topic)
            if prev is not None:
                p1,p2=participants(rows[prev]),participants(r)
                t1,t2=parsed_time(rows[prev][4]),parsed_time(r[4])
                close=True
                if t1 and t2:
                    try: close=abs((t2-t1).total_seconds()) <= 120*86400
                    except Exception: close=True
                if p1.intersection(p2) and close:
                    union(i,prev)
            by_topic_last[topic]=i
        groups: dict[int,list[int]]={}
        for i in range(n): groups.setdefault(find(i),[]).append(i)
        ordered=sorted(groups.values(),key=lambda g:min((rows[i][4] or '9999') for i in g))
        counts=db.counts(); cfg=self.cfg
        self.output.parent.mkdir(parents=True,exist_ok=True)
        with self.output.open('w',encoding='utf-8',newline='\n') as f:
            f.write('# PST Conversation Archive\n\n')
            f.write(f'- Generated: {now_iso()}\n- Source PST: `{Path(cfg.pst_path).name}`\n')
            f.write(f'- Filter addresses: {", ".join(cfg.emails) if cfg.emails else "(none: all mail)"}\n')
            fields=[x for x,on in [('FROM',cfg.match_from),('TO',cfg.match_to),('CC',cfg.match_cc),('BCC',cfg.match_bcc)] if on]
            f.write(f'- Match fields: {", ".join(fields)}\n- Threads: {len(ordered):,}\n- Messages: {counts["messages"]:,}\n')
            f.write(f'- Exact duplicate messages omitted: {counts["duplicates"]:,}\n- Extraction errors skipped: {counts["errors"]:,}\n')
            f.write('- Body format: plain text only; HTML/RTF formatting discarded.\n')
            if cfg.strip_quoted_history: f.write('- Reply-quoted prior history: best-effort removed; chronological messages below preserve the conversation sequence.\n')
            f.write('\n---\n\n')
            for ti,g in enumerate(ordered,1):
                g_sorted=sorted(g,key=lambda i:(rows[i][4] or '',rows[i][0]))
                first=rows[g_sorted[0]]; title=first[1] or '(no subject)'
                f.write(f'## Thread T{ti:06d} — {title}\n\n')
                f.write(f'- Messages: {len(g_sorted)}\n')
                dates=[rows[i][4] for i in g_sorted if rows[i][4]]
                if dates: f.write(f'- Period: {min(dates)} → {max(dates)}\n')
                f.write('\n')
                for mi,i in enumerate(g_sorted,1):
                    key=rows[i][0]
                    m=db.conn.execute('''SELECT folder_path,subject,sent_iso,sender_name,from_json,to_json,cc_json,bcc_json,body_z,duplicate_count
                                         FROM messages WHERE message_key=?''',(key,)).fetchone()
                    froms=json.loads(m[4] or '[]'); tos=json.loads(m[5] or '[]'); ccs=json.loads(m[6] or '[]'); bccs=json.loads(m[7] or '[]')
                    f.write(f'### {mi}. {m[2] or "(date unknown)"} — {m[1] or "(no subject)"}\n\n')
                    if froms: f.write(f'- From: {", ".join(froms)}\n')
                    if tos: f.write(f'- To: {", ".join(tos)}\n')
                    if ccs: f.write(f'- Cc: {", ".join(ccs)}\n')
                    if bccs: f.write(f'- Bcc: {", ".join(bccs)}\n')
                    f.write(f'- PST folder: `{m[0]}`\n')
                    if m[9]: f.write(f'- Duplicate copies omitted: {m[9]}\n')
                    body=decompress_text(m[8])
                    f.write('\n')
                    f.write(body if body else '[NO TEXT BODY]')
                    f.write('\n\n')
                    atts=db.conn.execute('SELECT attachment_key,filename,status,text_hash,error FROM attachments WHERE message_key=? ORDER BY attachment_index',(key,)).fetchall()
                    if atts:
                        f.write('#### Attachments\n\n')
                        for akey,fn,status,th,err in atts:
                            if th: f.write(f'- `{fn}` → ATT-{th[:16]}\n')
                            else: f.write(f'- `{fn}` → [{status}]\n')
                        f.write('\n')
                f.write('---\n\n')
            # Unique attachment text corpus: each exact text appears once globally.
            texts=db.conn.execute('SELECT text_hash,text_z,char_count FROM attachment_texts ORDER BY text_hash').fetchall()
            if texts:
                f.write('# Attachment Text Corpus\n\n')
                f.write('同一テキストの添付は1回だけ収録し、各メールから `ATT-...` で参照します。画像・OCR対象・未対応形式は本文化していません。\n\n')
                for th,blob,chars in texts:
                    names=[r[0] for r in db.conn.execute('SELECT DISTINCT filename FROM attachments WHERE text_hash=? ORDER BY filename LIMIT 8',(th,)).fetchall()]
                    f.write(f'## ATT-{th[:16]}\n\n')
                    if names: f.write(f'- Filename(s): {", ".join(f"`{x}`" for x in names)}\n')
                    f.write(f'- Characters: {chars:,}\n\n')
                    f.write(decompress_text(blob)); f.write('\n\n---\n\n')
            if counts['errors']:
                f.write('# Extraction Error Summary\n\n')
                f.write(f'{counts["errors"]:,}件のエラーを読み飛ばして処理を継続しました。正常完了時に再開DBを削除する設定では詳細ログは残りません。監査が必要な場合は「正常完了後も再開DBを残す」を有効にしてください。\n')
        self.emit('progress',phase='render',current=1,total=1,matched=self.matched)
        self.log(f'完成: {self.output}')


class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title(f'{APP_NAME} v{APP_VERSION}'); self.geometry('900x760'); self.minsize(800,680)
        self.q=queue.Queue(); self.cancel_event=threading.Event(); self.worker=None
        self._build(); self.after(100,self._pump)

    def _build(self):
        pad={'padx':8,'pady':5}
        frm=ttk.Frame(self); frm.pack(fill='both',expand=True,padx=12,pady=10)
        # Source/output
        io=ttk.LabelFrame(frm,text='1. PST / 出力'); io.pack(fill='x',pady=4)
        self.pst_var=tk.StringVar(); self.out_var=tk.StringVar()
        ttk.Label(io,text='PST').grid(row=0,column=0,sticky='w',**pad); ttk.Entry(io,textvariable=self.pst_var).grid(row=0,column=1,sticky='ew',**pad); ttk.Button(io,text='選択...',command=self._pick_pst).grid(row=0,column=2,**pad)
        ttk.Label(io,text='Markdown').grid(row=1,column=0,sticky='w',**pad); ttk.Entry(io,textvariable=self.out_var).grid(row=1,column=1,sticky='ew',**pad); ttk.Button(io,text='選択...',command=self._pick_out).grid(row=1,column=2,**pad)
        io.columnconfigure(1,weight=1)
        # Filters
        flt=ttk.LabelFrame(frm,text='2. 抽出対象メールアドレス（最大3つ / いずれか一致で採用）'); flt.pack(fill='x',pady=4)
        self.email_vars=[tk.StringVar() for _ in range(3)]
        for i,v in enumerate(self.email_vars): ttk.Label(flt,text=f'Address {i+1}').grid(row=i,column=0,sticky='w',**pad); ttk.Entry(flt,textvariable=v,width=55).grid(row=i,column=1,columnspan=4,sticky='ew',**pad)
        self.from_v=tk.BooleanVar(value=True); self.to_v=tk.BooleanVar(value=True); self.cc_v=tk.BooleanVar(value=True); self.bcc_v=tk.BooleanVar(value=True)
        ttk.Label(flt,text='一致を見る欄').grid(row=3,column=0,sticky='w',**pad)
        for col,(lab,var) in enumerate([('FROM',self.from_v),('TO',self.to_v),('CC',self.cc_v),('BCC',self.bcc_v)],1): ttk.Checkbutton(flt,text=lab,variable=var).grid(row=3,column=col,sticky='w',**pad)
        flt.columnconfigure(1,weight=1)
        # Options
        opt=ttk.LabelFrame(frm,text='3. 容量削減・速度・堅牢性'); opt.pack(fill='x',pady=4)
        self.attach_v=tk.BooleanVar(value=True); self.quote_v=tk.BooleanVar(value=True); self.dedupm_v=tk.BooleanVar(value=True); self.dedupa_v=tk.BooleanVar(value=True)
        self.formula_v=tk.BooleanVar(value=False); self.legacy_v=tk.BooleanVar(value=False); self.skip_v=tk.BooleanVar(value=True); self.keep_v=tk.BooleanVar(value=False)
        checks=[('添付の本文テキストも抽出',self.attach_v),('返信本文に埋め込まれた過去引用を除去（推奨）',self.quote_v),('完全重複メールを除去',self.dedupm_v),('同一添付テキストは1回だけ収録',self.dedupa_v),('Excel数式も収録（容量増）',self.formula_v),('旧 .doc/.xls/.ppt 添付もOfficeで変換（遅い）',self.legacy_v),('個別エラーを読み飛ばして継続',self.skip_v),('正常完了後も再開DBを残す',self.keep_v)]
        for i,(lab,var) in enumerate(checks): ttk.Checkbutton(opt,text=lab,variable=var).grid(row=i//2,column=i%2,sticky='w',padx=8,pady=3)
        adv=ttk.Frame(opt); adv.grid(row=4,column=0,columnspan=2,sticky='ew',padx=8,pady=5)
        ttk.Label(adv,text='Backend').pack(side='left'); self.backend_v=tk.StringVar(value='auto'); ttk.Combobox(adv,textvariable=self.backend_v,state='readonly',values=['auto','libpff','outlook'],width=12).pack(side='left',padx=(4,18))
        ttk.Label(adv,text='添付並列数').pack(side='left'); self.workers_v=tk.IntVar(value=min(8,max(2,os.cpu_count() or 4))); ttk.Spinbox(adv,from_=1,to=16,textvariable=self.workers_v,width=5).pack(side='left',padx=(4,18))
        ttk.Label(adv,text='添付最大MB').pack(side='left'); self.maxmb_v=tk.IntVar(value=250); ttk.Spinbox(adv,from_=1,to=4096,textvariable=self.maxmb_v,width=7).pack(side='left',padx=4)
        ttk.Label(opt,text='auto は libpff があれば高速直読、なければ Classic Outlook COM へフォールバックします。').grid(row=5,column=0,columnspan=2,sticky='w',padx=8,pady=2)
        # Resume controls
        res=ttk.LabelFrame(frm,text='4. 再開'); res.pack(fill='x',pady=4)
        self.resume_v=tk.BooleanVar(value=True); ttk.Checkbutton(res,text='既存のチェックポイントがあれば続きから再開',variable=self.resume_v).pack(anchor='w',padx=8,pady=4)
        ttk.Label(res,text='中断時は `<出力名>.partial.md` と `<出力.md>.work/checkpoint.sqlite3` が残ります。正常完了後はpartialを削除します。').pack(anchor='w',padx=8,pady=2)
        # Buttons and progress
        btn=ttk.Frame(frm); btn.pack(fill='x',pady=8)
        self.start_btn=ttk.Button(btn,text='抽出開始',command=self._start); self.start_btn.pack(side='left',padx=4)
        self.cancel_btn=ttk.Button(btn,text='中止',command=self._cancel,state='disabled'); self.cancel_btn.pack(side='left',padx=4)
        self.phase_lbl=ttk.Label(btn,text=''); self.phase_lbl.pack(side='left',padx=12)
        self.progress=ttk.Progressbar(frm,mode='determinate'); self.progress.pack(fill='x',pady=4)
        self.status=ttk.Label(frm,text=''); self.status.pack(anchor='w')
        logf=ttk.LabelFrame(frm,text='ログ'); logf.pack(fill='both',expand=True,pady=4)
        self.log=tk.Text(logf,height=14,wrap='word'); self.log.pack(fill='both',expand=True,padx=5,pady=5)

    def _pick_pst(self):
        p=filedialog.askopenfilename(filetypes=[('Outlook PST','*.pst'),('All files','*.*')])
        if p:
            self.pst_var.set(p)
            if not self.out_var.get(): self.out_var.set(str(Path(p).with_name(Path(p).stem+'_threads.md')))
    def _pick_out(self):
        p=filedialog.asksaveasfilename(defaultextension='.md',filetypes=[('Markdown','*.md')])
        if p:self.out_var.set(p)

    def _build_cfg(self) -> ExtractConfig:
        return ExtractConfig(self.pst_var.get().strip(),self.out_var.get().strip(),[v.get().strip() for v in self.email_vars],
                             self.from_v.get(),self.to_v.get(),self.cc_v.get(),self.bcc_v.get(),self.attach_v.get(),self.quote_v.get(),
                             self.dedupm_v.get(),self.dedupa_v.get(),self.formula_v.get(),self.legacy_v.get(),self.skip_v.get(),self.keep_v.get(),
                             self.backend_v.get(),self.workers_v.get(),self.maxmb_v.get()).normalized()

    def _start(self):
        try: cfg=self._build_cfg()
        except Exception as e: messagebox.showerror(APP_NAME,str(e)); return
        if not cfg.pst_path or not Path(cfg.pst_path).is_file(): messagebox.showerror(APP_NAME,'PSTファイルを選択してください。'); return
        if Path(cfg.pst_path).suffix.lower()!='.pst': messagebox.showerror(APP_NAME,'拡張子 .pst のファイルを選択してください。'); return
        if not cfg.output_path: messagebox.showerror(APP_NAME,'出力Markdownを指定してください。'); return
        if not any([cfg.match_from,cfg.match_to,cfg.match_cc,cfg.match_bcc]): messagebox.showerror(APP_NAME,'FROM/TO/CC/BCC の少なくとも1つを選択してください。'); return
        if not cfg.emails:
            if not messagebox.askyesno(APP_NAME,'メールアドレスが未入力です。PST内の全メールを対象にしますか？'): return
        work=Path(cfg.output_path+'.work'); dbp=work/'checkpoint.sqlite3'
        if dbp.exists():
            if not self.resume_v.get():
                if messagebox.askyesno(APP_NAME,'既存チェックポイントを削除して新規開始しますか？'):
                    shutil.rmtree(work,ignore_errors=True)
                else:return
            else:
                try:
                    test=WorkDB(dbp); old=test.get_meta('fingerprint'); test.close(); new=config_fingerprint(cfg)
                    if old and old!=new:
                        if messagebox.askyesno(APP_NAME,'既存チェックポイントは今回の設定と一致しません。削除して新規開始しますか？'):
                            shutil.rmtree(work,ignore_errors=True)
                        else:return
                except Exception as e:
                    if messagebox.askyesno(APP_NAME,f'チェックポイント確認に失敗しました。削除して新規開始しますか？\n{e}'):
                        shutil.rmtree(work,ignore_errors=True)
                    else:return
        self.cancel_event.clear(); self.start_btn.config(state='disabled'); self.cancel_btn.config(state='normal'); self.log.delete('1.0','end')
        self.worker=threading.Thread(target=Engine(cfg,self.q,self.cancel_event).run,daemon=True); self.worker.start()
    def _cancel(self): self.cancel_event.set(); self._append('中止要求を送信しました。安全な区切りで停止します。')
    def _append(self,text): self.log.insert('end',text+'\n'); self.log.see('end')
    def _pump(self):
        try:
            while True:
                kind,p=self.q.get_nowait()
                if kind=='log': self._append(p['text'])
                elif kind=='phase': self.phase_lbl.config(text=p['name']); self.progress['maximum']=max(1,p.get('total',1)); self.progress['value']=0
                elif kind=='progress':
                    total=max(1,p.get('total',1)); cur=p.get('current',0); self.progress['maximum']=total; self.progress['value']=cur
                    self.status.config(text=f'{p.get("phase","")}: {cur:,}/{total:,}  matched={p.get("matched",0):,}')
                elif kind=='done':
                    self.start_btn.config(state='normal'); self.cancel_btn.config(state='disabled'); self._append(f'完了: {p["output"]}')
                    messagebox.showinfo(APP_NAME,f'完了しました。\n{p["output"]}')
                elif kind=='cancelled': self.start_btn.config(state='normal'); self.cancel_btn.config(state='disabled')
                elif kind=='fatal':
                    self.start_btn.config(state='normal'); self.cancel_btn.config(state='disabled'); self._append(p['traceback']); messagebox.showerror(APP_NAME,p['error'])
        except queue.Empty: pass
        self.after(100,self._pump)


def self_test() -> int:
    """Packaged-build smoke test. Does not touch Outlook or user data."""
    result = Path.cwd() / 'PSTThreadExtractor_selftest.txt'
    try:
        import pypff  # type: ignore  # noqa:F401
        import pypdf  # type: ignore  # noqa:F401
        import extract_msg  # type: ignore  # noqa:F401
        import striprtf  # type: ignore  # noqa:F401
        with tempfile.TemporaryDirectory(prefix='pstx_selftest_') as td:
            t = Path(td)
            md = t / 'sample.md'
            md.write_text('# Title\n\nmarkdown body', encoding='utf-8')
            text, status = extract_attachment_path(md)
            assert status == 'OK' and 'markdown body' in text
            rtf = t / 'sample.rtf'
            rtf.write_bytes(br'{\rtf1\ansi Hello \b RTF\b0\par second line}')
            text, status = extract_attachment_path(rtf)
            assert status == 'OK' and 'Hello' in text and 'second line' in text
            db = WorkDB(t / 'smoke.sqlite3')
            db.set_meta('smoke', 'ok'); db.conn.commit()
            assert db.get_meta('smoke') == 'ok'
            db.close()
        result.write_text('OK\n', encoding='utf-8')
        return 0
    except Exception:
        try: result.write_text(traceback.format_exc(), encoding='utf-8')
        except Exception: pass
        return 2


def main():
    if '--self-test' in sys.argv:
        raise SystemExit(self_test())
    App().mainloop()

if __name__=='__main__': main()
