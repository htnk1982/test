"""Developer-only reproducible Windows x64 build using LLVM. Requires no Windows SDK.
Generates import libraries from the documented DLL export names. The final EXE
imports only operating-system DLLs. The manifest is embedded as a raw resource
with /manifest:no to avoid XML namespace/order changes during automatic merging.
The final embedded XML is checked byte-for-byte. This does not run Windows UI.
"""
from pathlib import Path
import shutil
import subprocess
import sys
from manifest_tools import write_manifest_res, verify_artifact
ROOT = Path(__file__).resolve().parent
DLLS = {
    'kernel32': '''GetModuleHandleW GetModuleFileNameW GetCurrentProcess GetProcAddress GetLastError ExitProcess GetLocalTime GetTimeZoneInformation GetTickCount64 GlobalMemoryStatusEx GetSystemPowerStatus GetEnvironmentVariableW CreateDirectoryW CreateFileW WriteFile FlushFileBuffers CloseHandle DeleteFileW WideCharToMultiByte GlobalAlloc GlobalLock GlobalUnlock GlobalFree ReadFile GetFileAttributesW CopyFileW MoveFileExW RemoveDirectoryW GetSystemDirectoryW GetDiskFreeSpaceExW CreateMutexW CreateThread CreateProcessW CreateJobObjectW SetInformationJobObject AssignProcessToJobObject TerminateJobObject TerminateProcess ResumeThread WaitForSingleObject GetExitCodeProcess MultiByteToWideChar''',
    'user32': '''RegisterClassExW CreateWindowExW DefWindowProcW ShowWindow UpdateWindow GetMessageW TranslateMessage DispatchMessageW PostQuitMessage DestroyWindow LoadCursorW SetWindowTextW SendMessageW MoveWindow GetClientRect EnableWindow MessageBoxW OpenClipboard EmptyClipboard SetClipboardData CloseClipboard SetProcessDPIAware IsDialogMessageW GetDC ReleaseDC PostMessageW SetTimer KillTimer''',
    'gdi32': 'GetDeviceCaps CreateFontW DeleteObject',
    'advapi32': 'RegOpenKeyExW RegQueryValueExW RegCloseKey',
    'setupapi': 'SetupDiGetClassDevsW SetupDiEnumDeviceInfo SetupDiGetDeviceRegistryPropertyW SetupDiDestroyDeviceInfoList',
    'cfgmgr32': 'CM_Get_DevNode_Status',
    'shell32': 'ShellExecuteW',
    'comdlg32': 'GetOpenFileNameW',
    'winmm': 'waveInGetNumDevs waveInGetDevCapsW waveInOpen waveInPrepareHeader waveInAddBuffer waveInStart waveInReset waveInUnprepareHeader waveInClose',
    'winhttp': 'WinHttpOpen WinHttpConnect WinHttpOpenRequest WinHttpSetTimeouts WinHttpSetOption WinHttpSendRequest WinHttpReceiveResponse WinHttpQueryHeaders WinHttpReadData WinHttpCloseHandle',
    'bcrypt': 'BCryptOpenAlgorithmProvider BCryptCreateHash BCryptHashData BCryptFinishHash BCryptDestroyHash BCryptCloseAlgorithmProvider',
}

def main():
    clang, link = shutil.which('clang'), shutil.which('lld-link')
    if not clang or not link:
        sys.exit('Developer build requires LLVM clang and lld-link. End users run the supplied EXE, not this script.')
    build = ROOT/'build'; build.mkdir(exist_ok=True)
    libs = []
    for dll, names in DLLS.items():
        definition = build/(dll+'.def')
        definition.write_text(f'LIBRARY {dll}.dll\nEXPORTS\n'+'\n'.join(names.split())+'\n', encoding='ascii')
        lib = build/(dll+'.lib')
        subprocess.run([link, '/lib', '/machine:x64', f'/def:{definition}', f'/out:{lib}'], check=True)
        libs.append(str(lib))
    objects=[]
    for name in ('text','app'):
        obj=build/(name+'.obj')
        subprocess.run([clang, '--target=x86_64-pc-windows-msvc', '-std=c11', '-ffreestanding', '-fno-stack-protector', '-funwind-tables', '-O2', '-Wall', '-Wextra', '-Werror', '-c', str(ROOT/'src'/f'{name}.c'), '-o', str(obj)], check=True)
        objects.append(str(obj))
    manifest=(ROOT/'src/app.manifest').read_bytes()
    resource=build/'app.res'
    write_manifest_res(manifest, resource)
    exe=ROOT/'LocalScribeNPU_InferenceTrial.exe'
    subprocess.run([link, '/machine:x64', '/subsystem:windows,6.02', '/entry:entry', '/nodefaultlib', '/dynamicbase', '/highentropyva', '/nxcompat', '/opt:ref', '/opt:icf', '/timestamp:0', '/manifest:no', str(resource), f'/out:{exe}', *objects, *libs], check=True)
    verify_artifact(exe, manifest)
    print(exe)
    print("PASS: embedded RT_MANIFEST/#1 exactly matches validated source")

if __name__ == '__main__': main()
