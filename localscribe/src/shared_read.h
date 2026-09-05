/* Shared mutable control files only. No deletion or ACL change is performed.
 * Include after the Win32 declarations (or the test harness declarations).
 */
#ifndef LOCALSCRIBE_SHARED_READ_H
#define LOCALSCRIBE_SHARED_READ_H
#define LS_SHARE_READ   0x00000001UL
#define LS_SHARE_WRITE  0x00000002UL
#define LS_SHARE_DELETE 0x00000004UL
#define LS_SIGNAL_SHARE (LS_SHARE_READ | LS_SHARE_WRITE | LS_SHARE_DELETE)
static int read_shared_file(LPCWSTR path, char *buffer, DWORD capacity, DWORD *count) {
    if (!buffer || !count || capacity < 2) return 0;
    *count = 0;
    HANDLE f = CreateFileW(path, 0x80000000, LS_SIGNAL_SHARE, 0, 3, 0x80, 0);
    if (f == INVALID_HANDLE_VALUE) return 0;
    BOOL read_ok = ReadFile(f, buffer, capacity - 1, count, 0);
    BOOL close_ok = CloseHandle(f);
    if (!read_ok || !close_ok || *count >= capacity) { *count = 0; return 0; }
    buffer[*count] = 0;
    return 1;
}
#endif
