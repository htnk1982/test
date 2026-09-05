"""Developer-side, fail-closed manifest embedding and artifact checks.

This checks the exact contract used by the LocalScribe diagnostic, not every
possible Windows manifest. It does not replace a Windows loader/GUI smoke test.
The PE reader walks RT_MANIFEST resources, rather than searching for a substring.
"""
from __future__ import annotations

from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

ASM1 = 'urn:schemas-microsoft-com:asm.v1'
ASM3 = 'urn:schemas-microsoft-com:asm.v3'
COMPAT = 'urn:schemas-microsoft-com:compatibility.v1'
DPI2005 = 'http://schemas.microsoft.com/SMI/2005/WindowsSettings'
APP_NAME = 'LocalScribe.NPU.InferenceTrial'
WINDOWS_ID = '{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}'


class ManifestError(ValueError):
    """The diagnostic's source or compiled artifact violates its contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def validate_manifest(data: bytes, expected_version: str | None = None) -> None:
    """Validate expanded XML names, ordering, privilege and dependency policy."""
    require(0 < len(data) <= 65536, 'Manifest size outside supported range')
    require(b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper(),
            'DTD/entity declarations are not permitted')
    try:
        root = ET.fromstring(data.decode('utf-8-sig'))
    except (ET.ParseError, UnicodeError) as exc:
        raise ManifestError('Invalid manifest XML/UTF-8') from exc
    require(root.tag == f'{{{ASM1}}}assembly', 'Wrong assembly namespace')
    require(root.attrib == {'manifestVersion': '1.0'}, 'Wrong assembly attributes')
    children = list(root)
    require(bool(children) and children[0].tag == f'{{{ASM1}}}assemblyIdentity',
            'assemblyIdentity must be the first child')
    identities = root.findall(f'{{{ASM1}}}assemblyIdentity')
    require(len(identities) == 1, 'Exactly one application identity required')
    identity = identities[0]
    require(identity.get('name') == APP_NAME, 'Wrong application identity')
    require(identity.get('type') == 'win32', 'Wrong application type')
    require(identity.get('processorArchitecture') == 'amd64', 'Wrong architecture')
    version = identity.get('version', '')
    require(re.fullmatch(r'\d{1,5}(?:\.\d{1,5}){3}', version) is not None,
            'Four-part assembly version required')
    require(all(int(part) <= 65535 for part in version.split('.')), 'Version out of range')
    if expected_version is not None:
        require(version == expected_version, 'Assembly version mismatch')
    require(set(identity.attrib) == {'name', 'type', 'processorArchitecture', 'version'},
            'Unexpected or namespaced identity attributes')
    require(len(identity) == 0, 'assemblyIdentity cannot have children')
    trusts = root.findall(f'{{{ASM3}}}trustInfo')
    require(len(trusts) == 1, 'Exactly one asm.v3 trustInfo required')
    require(len([e for e in root.iter() if e.tag.rsplit('}', 1)[-1] == 'trustInfo']) == 1,
            'Duplicate or mis-namespaced trustInfo')
    node = trusts[0]
    for local in ('security', 'requestedPrivileges', 'requestedExecutionLevel'):
        require(not node.attrib, 'Unexpected privilege container attributes')
        child_nodes = list(node)
        require(len(child_nodes) == 1 and child_nodes[0].tag == f'{{{ASM3}}}{local}',
                f'Invalid privilege structure/namespace at {local}')
        node = child_nodes[0]
    require(node.attrib == {'level': 'asInvoker', 'uiAccess': 'false'},
            'Unqualified asInvoker/uiAccess=false attributes required')
    require(len(node) == 0, 'requestedExecutionLevel must be empty')
    require(len([e for e in root.iter() if e.tag.rsplit('}', 1)[-1] == 'requestedExecutionLevel']) == 1,
            'Exactly one requestedExecutionLevel required')
    require(not any(e.tag.rsplit('}', 1)[-1] in ('dependency', 'dependentAssembly') for e in root.iter()),
            'Diagnostic must not add SxS runtime dependencies')
    compat = root.findall(f'{{{COMPAT}}}compatibility/{{{COMPAT}}}application/{{{COMPAT}}}supportedOS')
    require(len(compat) == 1 and compat[0].attrib == {'Id': WINDOWS_ID},
            'Windows compatibility declaration missing or invalid')
    dpi = root.findall(f'{{{ASM3}}}application/{{{ASM3}}}windowsSettings/{{{DPI2005}}}dpiAware')
    require(len(dpi) == 1 and (dpi[0].text or '').strip() == 'true',
            'DPI declaration missing or invalid')


def resource_record(data: bytes, resource_type: int, resource_id: int,
                    language_id: int = 0, flags: int = 0x30) -> bytes:
    """Encode one ordinal-ID Win32 .res record, preserving payload bytes."""
    for value in (resource_type, resource_id, language_id, flags):
        require(isinstance(value, int) and 0 <= value <= 65535, 'Resource field out of range')
    header = struct.pack('<IIHHHHIHHII', len(data), 32,
                         0xffff, resource_type, 0xffff, resource_id,
                         0, flags, language_id, 0, 0)
    return header + data + b'\0' * (-len(data) % 4)


def write_manifest_res(manifest: bytes, destination: Path) -> None:
    """Write RT_MANIFEST/#1/LANG_NEUTRAL without a linker XML merge."""
    validate_manifest(manifest)
    null_header = resource_record(b'', 0, 0, flags=0)
    destination.write_bytes(null_header + resource_record(manifest, 24, 1))


def extract_manifest_resources(binary: bytes) -> list[tuple[int, int, bytes]]:
    """Return (resource_id, language_id, XML bytes) from a Windows x64 PE.

    A bounds-checked, limited parser for this build's ordinal resources. Unused
    resource kinds are ignored. The result is empty if no resource directory.
    """
    def unpack(fmt: str, offset: int) -> tuple:
        require(0 <= offset and offset + struct.calcsize(fmt) <= len(binary),
                'Truncated PE structure')
        return struct.unpack_from(fmt, binary, offset)

    require(binary[:2] == b'MZ', 'Missing MZ header')
    pe = unpack('<I', 0x3c)[0]
    require(binary[pe:pe + 4] == b'PE\0\0', 'Missing PE signature')
    machine, section_count = unpack('<HH', pe + 4)
    require(machine == 0x8664, 'Not a Windows x64 executable')
    require(0 < section_count <= 96, 'Invalid PE section count')
    opt_size = unpack('<H', pe + 20)[0]
    opt = pe + 24
    require(opt_size >= 136 and unpack('<H', opt)[0] == 0x20b, 'Not PE32+')
    require(unpack('<I', opt + 108)[0] >= 3, 'Missing resource data-directory slot')
    rva, resource_size = unpack('<II', opt + 128)
    if not rva or not resource_size:
        return []
    sections = []
    for i in range(section_count):
        at = opt + opt_size + i * 40
        virtual_size, virtual_address, raw_size, raw_pointer = unpack('<IIII', at + 8)
        sections.append((virtual_address, raw_size, raw_pointer, virtual_size))

    def file_offset(address: int, length: int) -> int:
        for virtual_address, raw_size, raw_pointer, _ in sections:
            if virtual_address <= address and address + length <= virtual_address + raw_size:
                at = raw_pointer + address - virtual_address
                require(at + length <= len(binary), 'Truncated section payload')
                return at
        raise ManifestError('Resource RVA outside on-disk sections')

    base = file_offset(rva, resource_size)

    def relative(offset: int, size: int) -> int:
        require(0 <= offset and offset + size <= resource_size, 'Resource directory bounds error')
        return base + offset

    def entries(offset: int) -> list[tuple[int, int]]:
        at = relative(offset, 16)
        named, ordinal = unpack('<HH', at + 12)
        count = named + ordinal
        require(count <= 512, 'Resource directory too large')
        at = relative(offset + 16, count * 8)
        return [unpack('<II', at + 8 * i) for i in range(count)]

    result: list[tuple[int, int, bytes]] = []
    for resource_type, type_target in entries(0):
        if resource_type != 24:
            continue
        require(bool(type_target & 0x80000000), 'RT_MANIFEST must be a directory')
        for resource_id, name_target in entries(type_target & 0x7fffffff):
            require(not resource_id & 0x80000000, 'Named manifest IDs not supported')
            require(bool(name_target & 0x80000000), 'Manifest ID must be a directory')
            for language, language_target in entries(name_target & 0x7fffffff):
                require(not language & 0x80000000 and not language_target & 0x80000000,
                        'Invalid manifest language/data entry')
                data_rva, size, _, _ = unpack('<IIII', relative(language_target, 16))
                require(0 < size <= 65536, 'Embedded manifest size out of range')
                data_offset = file_offset(data_rva, size)
                result.append((resource_id, language, binary[data_offset:data_offset + size]))
    return result


def verify_artifact(exe: Path, source_manifest: bytes) -> bytes:
    """Fail if the final EXE changed the manifest at all, including namespaces."""
    resources = extract_manifest_resources(exe.read_bytes())
    require(len(resources) == 1, 'Exactly one embedded manifest resource required')
    resource_id, language, embedded = resources[0]
    require(resource_id == 1 and language == 0, 'Expected RT_MANIFEST/#1/LANG_NEUTRAL')
    validate_manifest(embedded)
    require(embedded == source_manifest, 'Embedded manifest differs from validated source')
    return embedded
