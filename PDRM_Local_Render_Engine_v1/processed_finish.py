"""Publish the unchanged distribution v2 chain to sibling processed/stem.wav,mp3.

DSP and the -12/-2 master -> -14 WAV -> MP3 path remain in distribution_finish.
Only verified completed audio is copied; original audio is never opened for write.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
import uuid
from target_settings import Targets

import distribution_finish as engine

VERSION = 'processed-finish-2.2.0'
io = engine.io


def default_work_root() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'processed_finish_v2_1'


def _redirected(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def _plain_dir(path: Path) -> None:
    if _redirected(path) or (path.exists() and not path.is_dir()):
        raise ValueError('Folder is a link or not a directory: ' + str(path))
    path.mkdir(parents=True, exist_ok=True)


def output_paths(source: Path) -> tuple[Path, dict[str, Path]]:
    source = Path(source).absolute()
    if not source.is_file() or source.suffix.lower() not in ('.wav', '.flac'):
        raise ValueError('Choose an existing original WAV/FLAC')
    # Renaming output to the original stem must not defeat double-processing protection.
    if any(p.name.casefold() == 'processed' for p in source.parents):
        raise ValueError('processed output is not a fresh input; choose the original')
    resolved = source.resolve(strict=True)
    if any(p.name.casefold() == 'processed' for p in resolved.parents):
        raise ValueError('processed output is not a fresh input; choose the original')
    folder = source.parent / 'processed'
    if _redirected(folder) or (folder.exists() and not folder.is_dir()):
        raise ValueError('processed must be a real directory')
    return folder, {ext: folder / (source.stem + '.' + ext) for ext in ('wav', 'mp3')}


def request_identity(source: Path, targets=None, backend=None) -> dict:
    selected = backend or engine
    targets = (targets if targets is not None else Targets()).validate()
    engine.legacy.verify_dsp()
    modules = ('distribution_finish.py', 'distribution_peak.py', 'accepted_finish.py',
               'note_sub_lab.py', 'note_sub_lab_v02.py', 'hf_temporal_contrast_lab.py', 'target_settings.py')
    modules = getattr(selected, 'IDENTITY_MODULES', modules)
    code = {name: hashlib.sha256(Path(__file__).with_name(name).read_text(encoding='utf-8-sig').encode('utf-8')).hexdigest()
            for name in modules}
    ff = io.ffmpeg_path()
    if not ff:
        raise RuntimeError('Existing FFmpeg not found; nothing was installed')
    return dict(source_name=source.name, source_sha256=io.file_hash(source),
                engine_version=selected.VERSION, code=code,
                versions={n: importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')},
                ffmpeg_sha256=io.file_hash(ff),
                targets=dict(wav_lufs=targets.wav_lufs, wav_tp_ceiling=targets.wav_tp,
                             mp3_lufs=targets.mp3_lufs, mp3_tp_ceiling=targets.mp3_tp))


def _check_outputs(folder: Path, paths: dict[str, Path], expected: dict | None) -> None:
    # Also reject case-only collisions on case-sensitive test machines.
    existing = {p.name.casefold(): p for p in folder.iterdir()}
    for dest in paths.values():
        other = existing.get(dest.name.casefold())
        if other is None:
            continue
        if (other.name != dest.name or _redirected(other) or not other.is_file() or
                expected is None or expected.get(dest.name) != io.file_hash(other)):
            raise RuntimeError('Name conflict or modified file; nothing overwritten: ' + str(other))


def _install_new(temp: Path, dest: Path) -> None:
    """Atomic single-file publication without replacing any pre-existing name.

    Windows rename refuses an existing destination. POSIX link is no-clobber.
    An unsupported filesystem is an error, not a reason to fall back to replace.
    The pair is journaled, not claimed to be a filesystem-wide atomic pair.
    """
    if os.name == 'nt':
        os.rename(temp, dest)
    else:
        os.link(temp, dest)
        temp.unlink()


def _check_replacement(folder, paths, new_files, old_files):
    # During an interrupted replacement only the journal's old/new exact bytes
    # may be present. Any user edit still blocks replacement.
    existing = {p.name.casefold(): p for p in folder.iterdir()}
    for dest in paths.values():
        p = existing.get(dest.name.casefold())
        if p is not None and (p.name != dest.name or _redirected(p) or not p.is_file() or
                io.file_hash(p) not in (new_files.get(dest.name), old_files.get(dest.name))):
            raise RuntimeError('Name conflict or modified file; nothing overwritten: '+str(p))


def run_file(source, work_root=None, *, interrupt_after=None, targets=None, replace_managed=False, backend=None) -> tuple[dict, Path]:
    selected = backend or engine
    source = Path(source).absolute()
    folder, paths = output_paths(source)
    if targets is not None: targets.validate()
    request = (request_identity(source, targets, backend=backend) if backend is not None else
               (request_identity(source) if targets is None else request_identity(source, targets)))
    work = Path(work_root) if work_root is not None else default_work_root()
    work = work.resolve()
    # Keep rendering and its large intermediate files out of the public folder.
    if work == folder.resolve() or folder.resolve() in work.parents:
        raise ValueError('Work folder must be outside processed')
    _plain_dir(folder)
    meta = folder / '.pdrm'
    _plain_dir(meta)
    key = hashlib.sha256(source.stem.casefold().encode('utf-8')).hexdigest()[:24]
    marker = meta / (key + '.json')
    lock = meta / (key + '.lock')
    if _redirected(lock) or _redirected(marker):
        raise RuntimeError('Linked state file refused')
    with io.job_lock(lock):
        saved = None
        replacing = False
        if marker.exists():
            saved = io.read_json(marker)
            if (saved.get('status') not in ('PUBLISHING','COMPLETE','REPLACING') or
                    set(saved.get('files', {})) != {p.name for p in paths.values()}):
                raise RuntimeError('Existing output belongs to another source/settings; nothing overwritten')
            if saved.get('request') != request:
                old = saved.get('request', {})
                same_source = (old.get('source_name') == request['source_name'] and
                               old.get('source_sha256') == request['source_sha256'])
                if not (replace_managed and same_source and saved['status'] == 'COMPLETE'):
                    raise RuntimeError('Existing output belongs to another source/settings; nothing overwritten. '
                                       '設定変更後の再作成は「既存出力を退避して作り直す」を選んでください。')
                replacing = True
            elif saved['status'] == 'REPLACING':
                replacing = True
        expected = saved['files'] if saved else None
        if saved and saved['status'] == 'REPLACING':
            _check_replacement(folder, paths, expected, saved['old_files'])
        else:
            _check_outputs(folder, paths, expected)
        if not replacing and saved and saved['status'] == 'COMPLETE' and all(p.exists() for p in paths.values()):
            return dict(saved, rerun_status='IDEMPOTENT_SKIP'), folder

        kwargs = dict(write_mp3=True)
        if targets is not None: kwargs['targets'] = targets
        report, final = selected.run_file(source, work, **kwargs)
        if (report.get('status') != 'COMPLETE' or not report.get('source_unchanged') or
                report.get('identity', {}).get('source_sha256') != request['source_sha256'] or
                io.file_hash(source) != request['source_sha256']):
            raise RuntimeError('Engine/source verification failed; nothing published')
        selected.verify_final(final, report['identity'])
        originals = {paths['wav'].name: final / selected.FILES[0], paths['mp3'].name: final / selected.FILES[2]}
        hashes = {name: io.file_hash(p) for name, p in originals.items()}
        if expected is not None and not (replacing and saved['status']=='COMPLETE') and hashes != expected:
            raise RuntimeError('Verified render differs from interrupted output; nothing overwritten')
        receipt = dict(version=VERSION, status='PUBLISHING', request=request, files=hashes,
                       render_result=str(final), master_metrics=report['master_metrics'],
                       codec_metrics=report['codec_metrics'],
                       chain=report.get('chain', 'HarmonicElasticity -> peak preparation -> Note-Sub -> HFTC -> release peak/gain'),
                       mp3_source='verified engine MP3 input WAV; no re-encoding by publisher')
        if replacing:
            if saved['status'] == 'REPLACING':
                backup = Path(saved['backup'])
                old_files = saved['old_files']
                _check_replacement(folder, paths, hashes, old_files)
                for name, expected_hash in old_files.items():
                    old_copy = backup/name
                    if old_copy.exists() and io.file_hash(old_copy) != expected_hash:
                        raise RuntimeError('Backup modified; nothing overwritten')
            else:
                _check_outputs(folder, paths, expected)
                backups = meta/'backups'
                _plain_dir(backups)
                backup = backups/(key+'_'+uuid.uuid4().hex[:12])
                backup.mkdir()
                old_files = dict(expected)
                for name, expected_hash in old_files.items():
                    original = folder/name
                    if original.exists():
                        shutil.copy2(original, backup/name)
                        if io.file_hash(backup/name) != expected_hash:
                            raise RuntimeError('Backup verification failed; current output preserved')
                        io.sync_owned_file(backup/name)
                io.atomic_json(backup/'receipt.json', saved)
            receipt.update(status='REPLACING', old_files=old_files, backup=str(backup))
        else:
            _check_outputs(folder, paths, expected)
        io.atomic_json(marker, receipt)
        # All backend WAV and MP3 QC has succeeded before either is exposed here.
        for i, (name, original) in enumerate(originals.items(), 1):
            dest = folder / name
            if replacing:
                _check_replacement(folder, paths, hashes, old_files)
            else:
                _check_outputs(folder, paths, hashes)
            if not dest.exists() or (replacing and io.file_hash(dest) != hashes[name]):
                fd, name_tmp = tempfile.mkstemp(prefix=key + '_', suffix='.partial', dir=meta)
                temp = Path(name_tmp)
                try:
                    with os.fdopen(fd, 'wb') as target, original.open('rb') as src:
                        shutil.copyfileobj(src, target, 4*1024*1024)
                        target.flush(); os.fsync(target.fileno())
                    if io.file_hash(temp) != hashes[name]:
                        raise RuntimeError('Copy verification failed')
                    if replacing and dest.exists():
                        _check_replacement(folder, paths, hashes, old_files)
                        os.replace(temp, dest)
                    else:
                        _install_new(temp, dest)
                finally:
                    temp.unlink(missing_ok=True)
            if interrupt_after == i:
                raise RuntimeError('TEST_INTERRUPTION_PUBLISH_' + str(i))
        _check_outputs(folder, paths, hashes)
        if not all(p.is_file() for p in paths.values()) or io.file_hash(source) != request['source_sha256']:
            raise RuntimeError('Publication/source verification failed')
        receipt['status'] = 'COMPLETE'
        io.atomic_json(marker, receipt)
        return receipt, folder


def choose_sources(sources):
    if sources:
        return [Path(s) for s in sources]
    import tkinter as tk
    from tkinter import filedialog
    app = tk.Tk(); app.withdraw()
    try:
        return [Path(s) for s in filedialog.askopenfilenames(
            title='未処理のWAV/FLACを選択（複数可・元フォルダのprocessedへ保存）',
            filetypes=[('Audio', '*.wav *.flac')])]
    finally:
        app.destroy()


def main(argv=None, *, backend=None, default_root=None) -> int:
    parser = argparse.ArgumentParser(description='Same-name WAV/MP3 in each source folder/processed')
    parser.add_argument('sources', nargs='*', type=Path)
    parser.add_argument('--work-root', type=Path, help='Internal render cache only; not the audio destination')
    for field in ('wav-lufs', 'wav-tp', 'mp3-lufs', 'mp3-tp'):
        parser.add_argument('--'+field, type=float)
    parser.add_argument('--replace-managed', action='store_true')
    args = parser.parse_args(argv)
    fields = {k:getattr(args,k) for k in Targets().to_dict()}
    targets = None
    if any(v is not None for v in fields.values()):
        targets = Targets(**{k:(v if v is not None else getattr(Targets(),k)) for k,v in fields.items()}).validate()
    sources = choose_sources(args.sources)
    if not sources:
        print('中止しました。原音は変更していません。'); return 0
    failed, folders = 0, []
    # Detect WAV/FLAC same-stem collisions before rendering either member.
    keys, conflicts = {}, set()
    for source in sources:
        key = (str(source.absolute().parent.resolve()).casefold(), source.stem.casefold())
        if key in keys and source.absolute() != keys[key]:
            conflicts.add(key)
        keys[key] = source.absolute()
    for i, source in enumerate(sources, 1):
        print(f'[{i}/{len(sources)}] {source.name}', flush=True)
        try:
            key = (str(source.absolute().parent.resolve()).casefold(), source.stem.casefold())
            if key in conflicts:
                raise RuntimeError('同じフォルダに同名のWAV/FLACが選ばれています。どちらか一方を選んでください。')
            kwargs = dict(targets=targets, replace_managed=args.replace_managed)
            if backend is not None: kwargs['backend'] = backend
            result, folder = run_file(source, args.work_root or default_root, **kwargs)
            print('確認済み（再処理なし）:' if result.get('rerun_status') else '完了:', folder, flush=True)
            for name in result['files']:
                print(' ', folder / name, flush=True)
            if folder not in folders: folders.append(folder)
        except Exception as exc:
            failed += 1
            print('未出力または保存未完了:', source.name, str(exc), flush=True)
            traceback.print_exc()
    # Do not open a separate Explorer window per track in a batch.
    if folders and os.name == 'nt':
        try: os.startfile(str(folders[0]))
        except OSError: pass
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
