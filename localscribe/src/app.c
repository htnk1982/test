/* LocalScribe NPU 0.2.3 — bounded inference trial, not the live transcription app.
 * Native Windows GUI + private, pinned Python runtime. No pip/PowerShell/SDK.
 * HTTPS downloads start only after the user accepts the preparation dialog.
 * Recording starts only on an explicit button press; never during NPU tests.
 */
#include "extra.h"
#include "text.h"
#include "shared_read.h"
#include <stdatomic.h>
#define W(s) ((LPCWSTR)L##s)
#define N(a) (sizeof(a)/sizeof((a)[0]))
#define DONE_MSG 0x8001
#define WM_WIM_DATA 0x3c0
void*memset(void*p,int v,SIZE_T n){volatile BYTE*q=p;while(n--)*q++=(BYTE)v;return p;}
void*memcpy(void*d,const void*s,SIZE_T n){BYTE*p=d;const BYTE*q=s;while(n--)*p++=*q++;return d;}
static HINSTANCE inst;static HWND win,title,info,setup,record,choose,compare,cancel,folder,mic,content,state,audiolabel;
static HFONT font,big;static int dpi=96,busy=0,recording=0,owned=0,exitAfter=0,operation=0;
static _Atomic int cancelled=0;static HANDLE worker,mutexHandle;
static WCHAR appdir[2048],home[2048],pythonDir[2304],pythonExe[2304],statusFile[2304],audioFile[4096],captureFile[2304],readyFile[2304],cancelFile[2304];
static WCHAR path1[4096],path2[4096],path3[4096],cmdline[16384],sysdir[2048],offline[2304],asset[2304],latest[4096];
static WCHAR statusText[8192];static char ioBuf[65536],uiBuf[32768];static WCHAR editBuf[16384];
static HANDLE wave;static WAVEHDR waveHeader;static short samples[320000];static QWORD captureStart;
static DWORD jobCode=0;static UINT micIDs[128];static int micCount=0;
static int px(int n){return n*dpi/96;}
static int is_cancelled(void){return atomic_load(&cancelled)!=0;}
static int exists(LPCWSTR p){return GetFileAttributesW(p)!=0xffffffff;}
static int dir(LPCWSTR p){return CreateDirectoryW(p,0)||GetLastError()==183;}
static int pathcat(LPWSTR dst,SIZE_T cap,LPCWSTR a,LPCWSTR b){Text t;text_init(&t,dst,cap);text_add(&t,a);text_add(&t,b);return !t.truncated;}
static int write_bytes(LPCWSTR p,const void*data,DWORD bytes){
 HANDLE f=CreateFileW(p,0x40000000,LS_SIGNAL_SHARE,0,2,0x80,0);if(f==INVALID_HANDLE_VALUE)return 0;
 DWORD done=0;BOOL ok=WriteFile(f,data,bytes,&done,0);if(ok&&done==bytes)ok=FlushFileBuffers(f);else ok=0;CloseHandle(f);return ok;
}
static void status(LPCWSTR s){int len=WideCharToMultiByte(65001,0,s,-1,ioBuf,sizeof ioBuf,0,0);if(len>0)write_bytes(statusFile,ioBuf,(DWORD)len-1);}
static void number_status(LPCWSTR a,QWORD n,LPCWSTR b){Text t;text_init(&t,statusText,N(statusText));text_add(&t,a);text_num(&t,n,0);text_add(&t,b);status(statusText);}
static void native_error(LPCWSTR message,DWORD code){
 Text t;text_init(&t,statusText,N(statusText));text_add(&t,W("未完了: "));text_add(&t,message);text_add(&t,W("（コード "));text_num(&t,code,0);text_add(&t,W("）"));status(statusText);
 pathcat(path3,N(path3),home,W("\\last_action.md"));
 text_init(&t,statusText,N(statusText));text_add(&t,W("# LocalScribe NPU — 操作結果\r\n\r\n- 状態: 未完了\r\n- 内容: "));text_add(&t,message);text_add(&t,W("\r\n- コード: "));text_num(&t,code,0);text_add(&t,W("\r\n\r\n設定変更・自動CPU代替・セキュリティ回避は行っていません。\r\n"));
 int len=WideCharToMultiByte(65001,0,statusText,-1,ioBuf,sizeof ioBuf,0,0);if(len>0)write_bytes(path3,ioBuf,len-1);
}
static int hash_python(LPCWSTR filename){
 static const char expected[]="76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0";
 static BYTE hashbuf[65536];BYTE digest[32];HANDLE alg=0,h=0;int ok=0;DWORD got=0;
 HANDLE f=CreateFileW(filename,0x80000000,1,0,3,0x80,0);if(f==INVALID_HANDLE_VALUE)return 0;
 if(BCryptOpenAlgorithmProvider(&alg,W("SHA256"),0,0)<0)goto finish;
 if(BCryptCreateHash(alg,&h,0,0,0,0,0)<0)goto finish;
 for(;;){if(!ReadFile(f,hashbuf,sizeof hashbuf,&got,0))goto finish;if(!got)break;if(BCryptHashData(h,hashbuf,got,0)<0)goto finish;}
 if(BCryptFinishHash(h,digest,32,0)<0)goto finish;ok=1;
 for(unsigned i=0;i<32;i++){static const char hex[]="0123456789abcdef";if(hex[digest[i]>>4]!=expected[2*i]||hex[digest[i]&15]!=expected[2*i+1])ok=0;}
 finish:if(h)BCryptDestroyHash(h);if(alg)BCryptCloseAlgorithmProvider(alg,0);CloseHandle(f);return ok;
}
static int get_python_zip(LPCWSTR output){
 HANDLE session=0,connection=0,request=0,f=INVALID_HANDLE_VALUE;int ok=0;DWORD failure=0;
 session=WinHttpOpen(W("LocalScribeNPU/0.2.3"),4,0,0,0);if(!session)goto done;
 if(!WinHttpSetTimeouts(session,10000,15000,30000,45000))goto done;
 connection=WinHttpConnect(session,W("www.python.org"),443,0);if(!connection)goto done;
 request=WinHttpOpenRequest(connection,W("GET"),W("/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip"),0,0,0,0x00800000);if(!request)goto done;
 DWORD policy=1;if(!WinHttpSetOption(request,88,&policy,4))goto done;
 if(!WinHttpSendRequest(request,0,0,0,0,0,0)||!WinHttpReceiveResponse(request,0))goto done;
 DWORD http=0,n=4;if(!WinHttpQueryHeaders(request,19|0x20000000,0,&http,&n,0))goto done;
 if(http!=200){failure=http;goto done;}
 f=CreateFileW(output,0x40000000,1,0,2,0x80,0);if(f==INVALID_HANDLE_VALUE)goto done;
 QWORD total=0;DWORD got=0,written=0;
 for(;;){if(is_cancelled()){failure=1223;goto done;}if(!WinHttpReadData(request,ioBuf,sizeof ioBuf,&got))goto done;if(!got)break;
  total+=got;if(total>30000000){failure=223;goto done;}
  if(!WriteFile(f,ioBuf,got,&written,0)||written!=got)goto done;
  if(total%(1024*1024)<65536)number_status(W("専用実行部品を取得中: "),total/1024,W(" KiB。初回のみ。"));
 }
 if(!FlushFileBuffers(f))goto done;ok=1;
 done:if(!ok&&!failure)failure=GetLastError();if(f!=INVALID_HANDLE_VALUE)CloseHandle(f);
 if(request)WinHttpCloseHandle(request);if(connection)WinHttpCloseHandle(connection);if(session)WinHttpCloseHandle(session);
 if(!ok){DeleteFileW(output);native_error(W("専用実行部品を取得できませんでした。保護設定は変更せず、last_action.mdを確認してください"),failure);}
 return ok;
}
static DWORD run_process(LPCWSTR exe,LPWSTR command,LPCWSTR cwd,DWORD maxms){
 STARTUPINFOW si;PROCESS_INFORMATION pi;SECURITY_ATTRIBUTES sa;JOB_EXTENDED limit;
 memset(&si,0,sizeof si);memset(&pi,0,sizeof pi);memset(&limit,0,sizeof limit);memset(&sa,0,sizeof sa);
 sa.nLength=sizeof sa;sa.bInheritHandle=1;
 // Persist errors privately, not to the shareable performance report.
 pathcat(path3,N(path3),home,W("\\_private_controller.log"));
 HANDLE log=CreateFileW(path3,0x40000000,3,&sa,2,0x80,0);
 HANDLE input=CreateFileW(W("NUL"),0x80000000,3,&sa,3,0x80,0);
 HANDLE job=CreateJobObjectW(0,0);if(!job){if(log!=INVALID_HANDLE_VALUE)CloseHandle(log);if(input!=INVALID_HANDLE_VALUE)CloseHandle(input);return 40001;}
 limit.BasicLimitInformation.LimitFlags=0x2000;
 if(!SetInformationJobObject(job,9,&limit,sizeof limit)){CloseHandle(job);if(log!=INVALID_HANDLE_VALUE)CloseHandle(log);if(input!=INVALID_HANDLE_VALUE)CloseHandle(input);return 40002;}
 si.cb=sizeof si;si.dwFlags=1;si.wShowWindow=0;
 if(log!=INVALID_HANDLE_VALUE&&input!=INVALID_HANDLE_VALUE){si.dwFlags|=0x100;si.hStdOutput=log;si.hStdError=log;si.hStdInput=input;}
 if(!CreateProcessW(exe,command,0,0,si.dwFlags&0x100?1:0,0x08000000|4,0,cwd,&si,&pi)){
  DWORD err=GetLastError();CloseHandle(job);if(log!=INVALID_HANDLE_VALUE)CloseHandle(log);if(input!=INVALID_HANDLE_VALUE)CloseHandle(input);return err?err:40003;
 }
 if(log!=INVALID_HANDLE_VALUE)CloseHandle(log);if(input!=INVALID_HANDLE_VALUE)CloseHandle(input);
 if(!AssignProcessToJobObject(job,pi.hProcess)){TerminateProcess(pi.hProcess,40004);CloseHandle(pi.hProcess);CloseHandle(pi.hThread);CloseHandle(job);return 40004;}
 if(ResumeThread(pi.hThread)==0xffffffff){TerminateJobObject(job,40005);CloseHandle(pi.hThread);CloseHandle(pi.hProcess);CloseHandle(job);return 40005;}
 CloseHandle(pi.hThread);DWORD code=0;QWORD start=GetTickCount64();QWORD cancelAt=0;
 for(;;){DWORD wait=WaitForSingleObject(pi.hProcess,200);if(wait==0){if(!GetExitCodeProcess(pi.hProcess,&code))code=40006;break;}if(wait==0xffffffff){code=40007;break;}
  if(is_cancelled()){
   if(!cancelAt){cancelAt=GetTickCount64();write_bytes(cancelFile,"cancel",6);}
   if(GetTickCount64()-cancelAt>3000){code=1223;TerminateJobObject(job,code);WaitForSingleObject(pi.hProcess,5000);break;}
  }
  if(GetTickCount64()-start>maxms){code=1460;TerminateJobObject(job,code);WaitForSingleObject(pi.hProcess,5000);break;}
 }
 CloseHandle(pi.hProcess);CloseHandle(job);return code;
}
static int bootstrap(void){
 // Restore a private runtime from a checksum-verified upstream archive. Existing
 // system Python installs and PATH are not modified.
 pathcat(path1,N(path1),home,W("\\python-3.13.12-embed-amd64.zip"));
 if(!hash_python(path1)){
  pathcat(path2,N(path2),offline,W("\\python-3.13.12-embed-amd64.zip"));
  if(hash_python(path2)){if(!CopyFileW(path2,path1,0)){native_error(W("オフライン部品のコピー失敗"),GetLastError());return 0;}}
  else {status(W("専用実行部品を取得中。利用者のPython環境は変更しません。"));if(!get_python_zip(path1))return 0;}
 }
 if(!hash_python(path1)){native_error(W("公式SHA-256と一致しないため展開しません"),40010);return 0;}
 if(is_cancelled())return 0;
 if(!dir(pythonDir)){native_error(W("専用フォルダの作成失敗"),GetLastError());return 0;}
 if(!GetSystemDirectoryW(sysdir,N(sysdir))||!pathcat(path2,N(path2),sysdir,W("\\tar.exe"))){native_error(W("Windowsの展開機能を見つけられません"),40011);return 0;}
 if(!exists(path2)){native_error(W("Windowsのtar.exeが見つかりません。設定変更は行いません"),40012);return 0;}
 Text t;text_init(&t,cmdline,N(cmdline));text_add(&t,W("\""));text_add(&t,path2);text_add(&t,W("\" -xf \""));text_add(&t,path1);text_add(&t,W("\" -C \""));text_add(&t,pythonDir);text_add(&t,W("\""));
 if(t.truncated){native_error(W("パスが長すぎます"),206);return 0;}
 status(W("専用実行部品を展開中。OS全体へのインストールは行いません。"));
 DWORD code=run_process(path2,cmdline,home,120000);if(code){native_error(W("専用実行部品の展開失敗"),code);return 0;}
 pathcat(path2,N(path2),pythonDir,W("\\python313._pth"));
 static const char pth[]="python313.zip\n.\nLib\\site-packages\n";
 if(!write_bytes(path2,pth,sizeof pth-1)){native_error(W("専用実行設定の保存失敗"),GetLastError());return 0;}
 if(!exists(pythonExe)){native_error(W("専用実行ファイルが不足しています"),40013);return 0;}
 return 1;
}
static DWORD CALL execute(void*unused){
 (void)unused;jobCode=0;DeleteFileW(cancelFile);
 if(operation==1&&!bootstrap()){jobCode=2;goto done;}
 if(is_cancelled()){jobCode=1223;goto done;}
 if(!exists(pythonExe)){native_error(W("先に「1 初回準備」を実行してください"),40020);jobCode=2;goto done;}
 Text t;text_init(&t,cmdline,N(cmdline));text_add(&t,W("\""));text_add(&t,pythonExe);text_add(&t,W("\" -I -B \""));text_add(&t,asset);text_add(&t,W("\" "));text_add(&t,operation==1?W("setup"):W("inspect"));text_add(&t,W(" --home \""));text_add(&t,home);text_add(&t,W("\""));
 if(operation==1){text_add(&t,W(" --offline \""));text_add(&t,offline);text_add(&t,W("\""));}
 else {text_add(&t,W(" --wav \""));text_add(&t,audioFile);text_add(&t,W("\""));if(owned)text_add(&t,W(" --owned-capture"));}
 if(t.truncated){native_error(W("パスが長すぎます"),206);jobCode=2;goto done;}
 jobCode=run_process(pythonExe,cmdline,home,operation==1?7200000:330000);
 if(jobCode!=0&&jobCode!=2)native_error(jobCode==1223?W("利用者の操作で中止しました。途中結果は残っています"):W("処理プロセスが正常終了しませんでした"),jobCode);
 done:if(is_cancelled()&&jobCode==0)jobCode=1223;PostMessageW(win,DONE_MSG,jobCode,0);return jobCode;
}
static void buttons(void){
 EnableWindow(setup,!busy&&!recording);EnableWindow(record,!busy&&!recording);EnableWindow(choose,!busy&&!recording);
 EnableWindow(compare,!busy&&!recording&&audioFile[0]&&exists(audioFile)&&exists(readyFile));
 EnableWindow(mic,!busy&&!recording);EnableWindow(cancel,busy||recording);
}
static void start_task(int which){
 if(busy||recording)return;
 if(which==1){if(MessageBoxW(win,W("初回のみ、公式配布元から専用実行部品とWhisperモデルを取得します（モデル約828MB＋実行部品）。\r\n\r\n・空き容量は4GB以上を確保してください。\r\n・Python／pip／開発SDKの手動導入は不要です。\r\n・通信はpython.org、PyPI、Hugging Faceと配布先CDNへの取得です。\r\n・会議音声や本文を送信しません。ドライバーや保護設定も変更しません。\r\n\r\n取得を開始しますか？"),W("初回準備の確認"),0x24)!=6)return;
  QWORD freeBytes=0;if(GetDiskFreeSpaceExW(home,&freeBytes,0,0)&&freeBytes<4000000000ULL){MessageBoxW(win,W("保存先の空き容量が4GB未満です。空き容量を確保してから実行してください。"),W("空き容量不足"),0x30);return;}
 }
 operation=which;busy=1;atomic_store(&cancelled,0);DeleteFileW(cancelFile);DeleteFileW(statusFile);buttons();
 SetWindowTextW(state,which==1?W("初回準備を開始します。"):W("CPUだけで原因を確認します。NPU・新しい録音・ダウンロードは実行しません。"));
 worker=CreateThread(0,0,execute,0,0,0);if(!worker){busy=0;buttons();MessageBoxW(win,W("処理を開始できませんでした。"),W("エラー"),0x10);}
}
static void little16(BYTE*p,WORD x){p[0]=(BYTE)x;p[1]=(BYTE)(x>>8);}
static void little32(BYTE*p,DWORD x){for(unsigned i=0;i<4;i++)p[i]=(BYTE)(x>>(8*i));}
static void finish_record(void){
 if(!recording)return;recording=0;
 UINT unprepare=waveInUnprepareHeader(wave,&waveHeader,sizeof waveHeader);UINT close=waveInClose(wave);wave=0;
 DWORD bytes=waveHeader.dwBytesRecorded&~1U;
 if(unprepare||close||bytes<64000||bytes>sizeof samples){SetWindowTextW(state,W("録音が短すぎるか、録音機器の終了に失敗しました。録音をやり直してください。"));buttons();return;}
 BYTE header[44];memset(header,0,44);memcpy(header,"RIFF",4);little32(header+4,bytes+36);memcpy(header+8,"WAVEfmt ",8);little32(header+16,16);little16(header+20,1);little16(header+22,1);little32(header+24,16000);little32(header+28,32000);little16(header+32,2);little16(header+34,16);memcpy(header+36,"data",4);little32(header+40,bytes);
 HANDLE f=CreateFileW(captureFile,0x40000000,1,0,2,0x80,0);DWORD a=0,b=0;int ok=0;
 if(f!=INVALID_HANDLE_VALUE){ok=WriteFile(f,header,44,&a,0)&&a==44&&WriteFile(f,samples,bytes,&b,0)&&b==bytes&&FlushFileBuffers(f);CloseHandle(f);}
 if(!ok){DeleteFileW(captureFile);SetWindowTextW(state,W("試験音声の保存に失敗しました。"));buttons();return;}
 pathcat(audioFile,N(audioFile),captureFile,W(""));owned=1;SetWindowTextW(audiolabel,W("試験音声：このアプリで録音した音声（外部送信なし）"));
 SetWindowTextW(state,W("録音を保存しました。「3 原因確認（CPUのみ）」を押してください。今回の確認後も録音を保持します。"));buttons();
}
static void start_record(void){
 if(busy||recording)return;
 if(exists(captureFile)&&MessageBoxW(win,W("前回の試験録音を、新しい録音で置き換えますか？"),W("試験音声の置換"),0x24)!=6)return;
 WAVEFORMATEX fmt;memset(&fmt,0,sizeof fmt);fmt.wFormatTag=1;fmt.nChannels=1;fmt.nSamplesPerSec=16000;fmt.nAvgBytesPerSec=32000;fmt.nBlockAlign=2;fmt.wBitsPerSample=16;
 int sel=(int)SendMessageW(mic,0x147,0,0);UINT id=sel>=0&&sel<micCount?micIDs[sel]:0xffffffff;
 UINT error=waveInOpen(&wave,id,&fmt,(SIZE_T)win,0,0x10000);
 if(error){SetWindowTextW(state,W("16kHzモノラルでマイクを開けません。別のマイク、または対応WAVを選択してください。"));return;}
 memset(&waveHeader,0,sizeof waveHeader);waveHeader.lpData=(char*)samples;waveHeader.dwBufferLength=sizeof samples;
 error=waveInPrepareHeader(wave,&waveHeader,sizeof waveHeader);
 if(error){waveInClose(wave);wave=0;SetWindowTextW(state,W("録音バッファを準備できませんでした。"));return;}
 error=waveInAddBuffer(wave,&waveHeader,sizeof waveHeader);
 if(error){waveInUnprepareHeader(wave,&waveHeader,sizeof waveHeader);waveInClose(wave);wave=0;SetWindowTextW(state,W("録音バッファを登録できませんでした。"));return;}
 recording=1;captureStart=GetTickCount64();buttons();error=waveInStart(wave);
 if(error){waveInReset(wave);finish_record();SetWindowTextW(state,W("マイク録音を開始できませんでした。"));return;}
 SetWindowTextW(state,W("録音中（最大20秒）。画面の例文を、普段の会話程度の速さで読んでください。"));
}
static void choose_wav(void){
 OPENFILENAMEW ofn;memset(&ofn,0,sizeof ofn);static WCHAR chosen[4096];chosen[0]=0;
 ofn.lStructSize=sizeof ofn;ofn.hwndOwner=win;ofn.lpstrFilter=W("WAV (16kHz mono PCM16, 2-29秒)\0*.wav\0\0");ofn.lpstrFile=chosen;ofn.nMaxFile=N(chosen);ofn.lpstrTitle=W("試験音声を選択（16kHz・モノラル・16bit PCM）");ofn.Flags=0x1000|0x800|8;
 if(GetOpenFileNameW(&ofn)){pathcat(audioFile,N(audioFile),chosen,W(""));owned=0;SetWindowTextW(audiolabel,W("試験音声：選択したWAV（元ファイルは変更・削除しません）"));buttons();}
}
static void poll_status(void){
 if(recording){Text t;text_init(&t,editBuf,N(editBuf));text_add(&t,W("録音中："));text_num(&t,(GetTickCount64()-captureStart)/1000,0);text_add(&t,W(" / 20秒。録音を終える場合は「中止／録音終了」。"));SetWindowTextW(state,editBuf);return;}
 if(!busy)return;
 DWORD n=0;
 if(read_shared_file(statusFile,uiBuf,sizeof uiBuf,&n)&&n){
  // The read handle is already closed; painting cannot extend a file lock.
  int len=MultiByteToWideChar(65001,0,uiBuf,n,editBuf,N(editBuf)-1);
  if(len>0){editBuf[len]=0;SetWindowTextW(state,editBuf);}
 }

}
static void show_folder(void){
 static WCHAR filepath[2304];pathcat(filepath,N(filepath),home,W("\\latest_report.txt"));
 DWORD n=0;latest[0]=0;
 if(read_shared_file(filepath,uiBuf,sizeof uiBuf,&n)&&n){int len=MultiByteToWideChar(65001,0,uiBuf,n,latest,N(latest)-1);if(len>0){latest[len]=0;for(int i=len-1;i>=0;i--)if(latest[i]=='\\'||latest[i]=='/'){latest[i]=0;break;}}}
 ShellExecuteW(win,W("open"),latest[0]&&operation==2?latest:home,0,0,1);
}
static HWND control(LPCWSTR cls,LPCWSTR txt,DWORD style,int id){HWND h=CreateWindowExW(0,cls,txt,0x40000000|0x10000000|style,0,0,0,0,win,(HMENU)(SIZE_T)id,inst,0);SendMessageW(h,0x30,(WPARAM)font,1);return h;}
static void layout(void){RECT r;GetClientRect(win,&r);int w=r.right*96/dpi,h=r.bottom*96/dpi;
 MoveWindow(title,px(24),px(18),px(w-48),px(36),1);MoveWindow(info,px(24),px(62),px(w-48),px(76),1);
 MoveWindow(setup,px(24),px(148),px(190),px(44),1);MoveWindow(record,px(224),px(148),px(185),px(44),1);MoveWindow(compare,px(419),px(148),px(218),px(44),1);MoveWindow(cancel,px(647),px(148),px(180),px(44),1);
 MoveWindow(mic,px(24),px(209),px(445),px(280),1);MoveWindow(choose,px(482),px(208),px(180),px(36),1);MoveWindow(folder,px(674),px(208),px(185),px(36),1);
 MoveWindow(audiolabel,px(24),px(256),px(w-48),px(44),1);MoveWindow(content,px(24),px(307),px(w-48),px(h-425),1);MoveWindow(state,px(24),px(h-100),px(w-48),px(84),1);
}
static LRESULT CALL proc(HWND w,UINT m,WPARAM wp,LPARAM lp){
 switch(m){
 case 1:win=w;
  title=control(W("STATIC"),W("LocalScribe NPU｜原因確認 0.2.3"),0,0);SendMessageW(title,0x30,(WPARAM)big,1);
  info=control(W("STATIC"),W("既存のモデル・実行部品・録音を使い、CPU側の失敗原因を確認します。NPUは起動しません。\r\nv0.2.2で初回準備済みなら、再準備・再録音をせず「3 原因確認（CPUのみ）」を押してください。\r\n各試験は最大120秒。モデルロード失敗時のみ、キャッシュ指定なしで追加1回。"),0,0);
  setup=control(W("BUTTON"),W("初回準備（通常不要）"),0x10000,101);record=control(W("BUTTON"),W("録音（音声なし時）"),0x10000,102);compare=control(W("BUTTON"),W("3 原因確認（CPUのみ）"),0x10000,103);cancel=control(W("BUTTON"),W("中止／録音終了"),0x10000,104);
  mic=control(W("COMBOBOX"),W(""),0x10000|0x200000|3,105);
  SendMessageW(mic,0x143,0,(LPARAM)W("マイク：Windowsの既定入力"));micIDs[0]=0xffffffff;micCount=1;
  for(UINT i=0;i<waveInGetNumDevs()&&micCount<128;i++){WAVEINCAPSW caps;memset(&caps,0,sizeof caps);if(!waveInGetDevCapsW(i,&caps,sizeof caps)){caps.szPname[31]=0;SendMessageW(mic,0x143,0,(LPARAM)caps.szPname);micIDs[micCount++]=i;}}
  SendMessageW(mic,0x14e,0,0);choose=control(W("BUTTON"),W("WAVを選択"),0x10000,106);folder=control(W("BUTTON"),W("結果フォルダ"),0x10000,107);
  audiolabel=control(W("STATIC"),W("試験音声：未選択。初回準備後に20秒録音します。"),0,0);
  content=CreateWindowExW(0x200,W("EDIT"),W("【今回の操作】\r\n前回の録音が残っていれば「3 原因確認（CPUのみ）」を押すだけです。\r\n初回準備のやり直し、モデル再取得、NPU再コンパイルは不要です。\r\n\r\n【確認内容】\r\n1. 既存モデルの整合性とCPUキャッシュ設定でWhisperを1回試します。\r\n2. モデルロード失敗時だけ、別プロセスでキャッシュ指定を外して1回試します。\r\n・各試験の上限は120秒です。タイムアウトは非対応の証明ではありません。\r\n・NPU推論へは進みません。録音・キャッシュは削除しません。\r\n・「結果フォルダ」の LocalScribe_原因確認.md を共有してください。\r\n・例外のパス等を自動マスクしますが、共有前に内容をご確認ください。\r\n・_private_ で始まるログや音声は共有不要です。\r\n\r\n【録音がない場合の例文】\r\n今日は文字起こしの動作確認です。来週の月曜日に在庫を確認します。\r\n数量は百二十台です。出荷日は、まだ決まっていません。\r\n\r\nこの版は原因確認用です。リアルタイム文字起こし本体は未完成です。"),0x40000000|0x10000000|0x10000|0x200000|4|0x40|0x800,0,0,0,0,w,(HMENU)108,inst,0);SendMessageW(content,0x30,(WPARAM)font,1);
  state=control(W("STATIC"),W("v0.2.2で準備済みなら、そのまま「3 原因確認（CPUのみ）」を押してください。"),0,0);buttons();layout();SetTimer(w,1,400,0);return 0;
 case 5:if(title)layout();return 0;
 case 0x24:{MINMAXINFO*p=(MINMAXINFO*)lp;p->ptMinTrackSize.x=px(910);p->ptMinTrackSize.y=px(600);return 0;}
 case 0x113:poll_status();return 0;
 case WM_WIM_DATA:if(recording&&(WAVEHDR*)lp==&waveHeader)finish_record();return 0;
 case DONE_MSG:
  poll_status();busy=0;if(worker){CloseHandle(worker);worker=0;}buttons();
  // Completion comes from the process exit status, NOT the progress file.
  if(wp==0)SetWindowTextW(state,operation==1?W("初回準備が完了しました。試験音声を選び「3 原因確認（CPUのみ）」を押してください。"):W("原因確認のレポートを保存しました。推論成功とは別です。「結果フォルダ」を開いてください。"));
  else if(wp==1223)SetWindowTextW(state,W("中止しました。取得済みファイルと途中結果は残しています。"));
  else SetWindowTextW(state,operation==2?W("原因確認で停止しました。「結果フォルダ」の LocalScribe_原因確認.md を確認してください。"):W("準備は未完了です。「結果フォルダ」の setup_report.md または last_action.md を確認してください。"));
  if(exitAfter)DestroyWindow(w);return 0;
 case 0x111:switch(wp&0xffff){case 101:start_task(1);break;case 102:start_record();break;case 103:start_task(2);break;
  case 104:if(recording){waveInReset(wave);finish_record();}else if(busy){atomic_store(&cancelled,1);write_bytes(cancelFile,"cancel",6);SetWindowTextW(state,W("中止を要求しました。通信中の場合、終了まで最大45秒程度かかることがあります。"));}break;
  case 106:choose_wav();break;case 107:show_folder();break;}return 0;
 case 0x10:if(busy){if(MessageBoxW(w,W("処理を中止して終了しますか？ 未完了の試験音声と途中結果は残ります。"),W("終了確認"),0x24)==6){exitAfter=1;atomic_store(&cancelled,1);write_bytes(cancelFile,"cancel",6);}return 0;}if(recording){waveInReset(wave);finish_record();}DestroyWindow(w);return 0;
 case 2:KillTimer(w,1);PostQuitMessage(0);return 0;
 }return DefWindowProcW(w,m,wp,lp);
}
void entry(void){
 inst=GetModuleHandleW(0);DWORD n=GetModuleFileNameW(0,appdir,N(appdir));if(!n||n>=N(appdir))ExitProcess(10);
 while(n&&appdir[n]!='\\'&&appdir[n]!='/')n--;appdir[n]=0;
 n=GetEnvironmentVariableW(W("LOCALAPPDATA"),home,N(home));if(!n||n>=N(home)-100)ExitProcess(11);
 Text t;text_init(&t,path1,N(path1));text_add(&t,home);text_add(&t,W("\\LocalScribeNPU"));if(!dir(path1))ExitProcess(12);
 text_add(&t,W("\\InferenceTrial020"));if(!dir(path1))ExitProcess(13);pathcat(home,N(home),path1,W(""));
 pathcat(pythonDir,N(pythonDir),home,W("\\python313"));pathcat(pythonExe,N(pythonExe),pythonDir,W("\\python.exe"));pathcat(statusFile,N(statusFile),home,W("\\status.txt"));pathcat(readyFile,N(readyFile),home,W("\\ready.json"));pathcat(cancelFile,N(cancelFile),home,W("\\cancel.flag"));pathcat(captureFile,N(captureFile),home,W("\\capture_test.wav"));pathcat(asset,N(asset),appdir,W("\\assets\\task.py"));pathcat(offline,N(offline),appdir,W("\\offline"));
 mutexHandle=CreateMutexW(0,0,W("Local\\LocalScribeNPUInferenceTrial020"));if(!mutexHandle||GetLastError()==183){MessageBoxW(0,W("同じ推論試験アプリが既に起動しています。"),W("LocalScribe NPU"),0x30);ExitProcess(14);}
 if(!exists(asset)){MessageBoxW(0,W("assetsフォルダが見つかりません。ZIPを「すべて展開」してから起動してください。EXEだけを移動しないでください。"),W("必要ファイル不足"),0x10);ExitProcess(15);}
 DeleteFileW(statusFile);DeleteFileW(cancelFile);
 if(exists(captureFile)){pathcat(audioFile,N(audioFile),captureFile,W(""));owned=1;}
 SetProcessDPIAware();HDC dc=GetDC(0);if(dc){int d=GetDeviceCaps(dc,90);if(d>=96&&d<=384)dpi=d;ReleaseDC(0,dc);}
 font=CreateFontW(-px(16),0,0,0,400,0,0,0,1,0,0,5,0,W("Yu Gothic UI"));big=CreateFontW(-px(25),0,0,0,600,0,0,0,1,0,0,5,0,W("Yu Gothic UI"));
 WNDCLASSEXW wc;memset(&wc,0,sizeof wc);wc.cbSize=sizeof wc;wc.lpfnWndProc=proc;wc.hInstance=inst;wc.hCursor=LoadCursorW(0,(LPCWSTR)32512);wc.hbrBackground=(HBRUSH)6;wc.lpszClassName=W("LocalScribeInference020");if(!RegisterClassExW(&wc))ExitProcess(16);
 win=CreateWindowExW(0x10000,wc.lpszClassName,W("LocalScribe NPU — 原因確認 0.2.3"),0x00cf0000,0x80000000,0x80000000,px(980),px(760),0,0,inst,0);if(!win)ExitProcess(17);ShowWindow(win,1);UpdateWindow(win);
 if(audioFile[0])SetWindowTextW(audiolabel,W("試験音声：前回の未完了の録音を再利用できます。"));
 MSG msg;int result;while((result=GetMessageW(&msg,0,0,0))>0){if(!IsDialogMessageW(win,&msg)){TranslateMessage(&msg);DispatchMessageW(&msg);}}
 if(font)DeleteObject(font);if(big)DeleteObject(big);if(mutexHandle)CloseHandle(mutexHandle);ExitProcess(result<0?18:0);
}
