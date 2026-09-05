/* Minimal Windows x64 ABI declarations. No SDK or third-party runtime is linked. */
#ifndef WINMINI_H
#define WINMINI_H

typedef unsigned short WCHAR;
typedef unsigned char BYTE;
typedef unsigned short WORD;
typedef unsigned int UINT;
typedef unsigned long DWORD;
typedef long LONG;
typedef int BOOL;
typedef unsigned long long QWORD;
typedef unsigned long long SIZE_T;
typedef unsigned long long WPARAM;
typedef long long LPARAM;
typedef long long LRESULT;
typedef void *HANDLE;
typedef HANDLE HWND;
typedef HANDLE HINSTANCE;
typedef HANDLE HKEY;
typedef HANDLE HDC;
typedef HANDLE HBRUSH;
typedef HANDLE HICON;
typedef HANDLE HCURSOR;
typedef HANDLE HMENU;
typedef HANDLE HFONT;
typedef const WCHAR *LPCWSTR;
typedef WCHAR *LPWSTR;
#define API __declspec(dllimport)
#define CALL __stdcall
#define NULL ((void *)0)
#define INVALID_HANDLE_VALUE ((HANDLE)(long long)-1)
#define HKEY_LOCAL_MACHINE ((HKEY)(long long)(long)0x80000002)

typedef struct { LONG x,y; } POINT;
typedef struct { LONG left,top,right,bottom; } RECT;
typedef struct { HWND hwnd; UINT message; WPARAM wParam; LPARAM lParam; DWORD time; POINT pt; DWORD lPrivate; } MSG;
typedef LRESULT (CALL *WNDPROC)(HWND,UINT,WPARAM,LPARAM);
typedef struct { UINT cbSize,style; WNDPROC lpfnWndProc; int cbClsExtra,cbWndExtra; HINSTANCE hInstance; HICON hIcon; HCURSOR hCursor; HBRUSH hbrBackground; LPCWSTR lpszMenuName,lpszClassName; HICON hIconSm; } WNDCLASSEXW;
typedef struct { POINT ptReserved,ptMaxSize,ptMaxPosition,ptMinTrackSize,ptMaxTrackSize; } MINMAXINFO;
typedef struct { WORD wYear,wMonth,wDayOfWeek,wDay,wHour,wMinute,wSecond,wMilliseconds; } SYSTEMTIME;
typedef struct { DWORD dwLength,dwMemoryLoad; QWORD ullTotalPhys,ullAvailPhys,ullTotalPageFile,ullAvailPageFile,ullTotalVirtual,ullAvailVirtual,ullAvailExtendedVirtual; } MEMORYSTATUSEX;
typedef struct { BYTE ACLineStatus,BatteryFlag,BatteryLifePercent,SystemStatusFlag; DWORD BatteryLifeTime,BatteryFullLifeTime; } SYSTEM_POWER_STATUS;
typedef struct { DWORD Data1; WORD Data2,Data3; BYTE Data4[8]; } GUID;
typedef struct { DWORD cbSize; GUID ClassGuid; DWORD DevInst; SIZE_T Reserved; } SP_DEVINFO_DATA;
typedef struct { LONG Bias; WCHAR StandardName[32]; SYSTEMTIME StandardDate; LONG StandardBias; WCHAR DaylightName[32]; SYSTEMTIME DaylightDate; LONG DaylightBias; } TIME_ZONE_INFORMATION;

API HINSTANCE CALL GetModuleHandleW(LPCWSTR);
API DWORD CALL GetModuleFileNameW(HINSTANCE,LPWSTR,DWORD);
API HANDLE CALL GetCurrentProcess(void);
API void * CALL GetProcAddress(HINSTANCE,const char*);
API DWORD CALL GetLastError(void);
API void CALL ExitProcess(UINT);
API void CALL GetLocalTime(SYSTEMTIME*);
API DWORD CALL GetTimeZoneInformation(TIME_ZONE_INFORMATION*);
API QWORD CALL GetTickCount64(void);
API BOOL CALL GlobalMemoryStatusEx(MEMORYSTATUSEX*);
API BOOL CALL GetSystemPowerStatus(SYSTEM_POWER_STATUS*);
API DWORD CALL GetEnvironmentVariableW(LPCWSTR,LPWSTR,DWORD);
API BOOL CALL CreateDirectoryW(LPCWSTR,void*);
API HANDLE CALL CreateFileW(LPCWSTR,DWORD,DWORD,void*,DWORD,DWORD,HANDLE);
API BOOL CALL WriteFile(HANDLE,const void*,DWORD,DWORD*,void*);
API BOOL CALL FlushFileBuffers(HANDLE);
API BOOL CALL CloseHandle(HANDLE);
API BOOL CALL DeleteFileW(LPCWSTR);
API int CALL WideCharToMultiByte(UINT,DWORD,LPCWSTR,int,char*,int,const char*,BOOL*);
API HANDLE CALL GlobalAlloc(UINT,SIZE_T);
API void * CALL GlobalLock(HANDLE);
API BOOL CALL GlobalUnlock(HANDLE);
API HANDLE CALL GlobalFree(HANDLE);

API WORD CALL RegisterClassExW(const WNDCLASSEXW*);
API HWND CALL CreateWindowExW(DWORD,LPCWSTR,LPCWSTR,DWORD,int,int,int,int,HWND,HMENU,HINSTANCE,void*);
API LRESULT CALL DefWindowProcW(HWND,UINT,WPARAM,LPARAM);
API BOOL CALL ShowWindow(HWND,int);
API BOOL CALL UpdateWindow(HWND);
API BOOL CALL GetMessageW(MSG*,HWND,UINT,UINT);
API BOOL CALL TranslateMessage(const MSG*);
API LRESULT CALL DispatchMessageW(const MSG*);
API void CALL PostQuitMessage(int);
API BOOL CALL DestroyWindow(HWND);
API HCURSOR CALL LoadCursorW(HINSTANCE,LPCWSTR);
API BOOL CALL SetWindowTextW(HWND,LPCWSTR);
API LRESULT CALL SendMessageW(HWND,UINT,WPARAM,LPARAM);
API BOOL CALL MoveWindow(HWND,int,int,int,int,BOOL);
API BOOL CALL GetClientRect(HWND,RECT*);
API BOOL CALL EnableWindow(HWND,BOOL);
API int CALL MessageBoxW(HWND,LPCWSTR,LPCWSTR,UINT);
API BOOL CALL OpenClipboard(HWND);
API BOOL CALL EmptyClipboard(void);
API HANDLE CALL SetClipboardData(UINT,HANDLE);
API BOOL CALL CloseClipboard(void);
API BOOL CALL SetProcessDPIAware(void);
API BOOL CALL IsDialogMessageW(HWND,MSG*);
API HDC CALL GetDC(HWND);
API int CALL ReleaseDC(HWND,HDC);
API int CALL GetDeviceCaps(HDC,int);
API HFONT CALL CreateFontW(int,int,int,int,int,DWORD,DWORD,DWORD,DWORD,DWORD,DWORD,DWORD,DWORD,LPCWSTR);
API BOOL CALL DeleteObject(HANDLE);
API LONG CALL RegOpenKeyExW(HKEY,LPCWSTR,DWORD,DWORD,HKEY*);
API LONG CALL RegQueryValueExW(HKEY,LPCWSTR,DWORD*,DWORD*,BYTE*,DWORD*);
API LONG CALL RegCloseKey(HKEY);
API HANDLE CALL SetupDiGetClassDevsW(const GUID*,LPCWSTR,HWND,DWORD);
API BOOL CALL SetupDiEnumDeviceInfo(HANDLE,DWORD,SP_DEVINFO_DATA*);
API BOOL CALL SetupDiGetDeviceRegistryPropertyW(HANDLE,SP_DEVINFO_DATA*,DWORD,DWORD*,BYTE*,DWORD,DWORD*);
API BOOL CALL SetupDiDestroyDeviceInfoList(HANDLE);
API DWORD CALL CM_Get_DevNode_Status(DWORD*,DWORD*,DWORD,DWORD);
API HINSTANCE CALL ShellExecuteW(HWND,LPCWSTR,LPCWSTR,LPCWSTR,LPCWSTR,int);

_Static_assert(sizeof(DWORD)==4,"DWORD must be 32-bit");
_Static_assert(sizeof(WCHAR)==2,"UTF-16 ABI");
_Static_assert(sizeof(void*)==8,"x64 only");
_Static_assert(sizeof(WNDCLASSEXW)==80,"WNDCLASSEXW ABI");
_Static_assert(sizeof(MSG)==48,"MSG ABI");
_Static_assert(sizeof(SP_DEVINFO_DATA)==32,"SP_DEVINFO_DATA ABI");
_Static_assert(sizeof(MEMORYSTATUSEX)==64,"MEMORYSTATUSEX ABI");
#endif
