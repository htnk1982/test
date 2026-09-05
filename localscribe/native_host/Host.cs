// Visible desktop host. Owns one fixed bundled worker; no downloads, recording or process enumeration.
using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Drawing;
using System.Diagnostics;
using System.Collections.Generic;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

sealed class OwnedJob : IDisposable {
    [StructLayout(LayoutKind.Sequential)] struct Basic {
        public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinWorkingSet, MaxWorkingSet;
        public uint ActiveProcesses; public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct Io {
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct Extended {
        public Basic Limits; public Io Counters; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern SafeFileHandle CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(SafeFileHandle job, int info, ref Extended limits, uint size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(SafeFileHandle job, IntPtr process);
    SafeFileHandle handle;
    public OwnedJob() {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception();
        Extended limits = new Extended(); limits.Limits.Flags = 0x2000;
        if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(typeof(Extended)))) {
            int code = Marshal.GetLastWin32Error(); handle.Dispose(); throw new System.ComponentModel.Win32Exception(code);
        }
    }
    public void Attach(Process ownedChild) {
        if (!AssignProcessToJobObject(handle, ownedChild.Handle)) throw new System.ComponentModel.Win32Exception();
    }
    public void Dispose() { handle.Dispose(); }
}

sealed class Host : Form {
    const string Version = "0.5.0-bounded-file-candidate";
    readonly TextBox audio = new TextBox(), display = new TextBox();
    readonly ComboBox device = new ComboBox();
    readonly Button choose = new Button(), start = new Button(), cancel = new Button(), folder = new Button();
    readonly Label status = new Label(), note = new Label();
    readonly string baseDir = AppDomain.CurrentDomain.BaseDirectory;
    string outputRoot, activeDir, phase = "idle", cancellation = null;
    bool busy, closeRequested, exercise;
    string testCase = "normal";
    double testLimit;
    Process child;
    OwnedJob job;
    public Task<Dictionary<string, object>> ActiveTask;
    public Dictionary<string, object> Last;
    public Action<string> PhaseSeen;
    readonly Stopwatch uiClock = Stopwatch.StartNew();
    double lastTick, maxGap, startupSeconds;
    string maxGapPhase="not-started";
    bool shown;
    readonly System.Windows.Forms.Timer heartbeat = new System.Windows.Forms.Timer();

    public Host(string output, bool testing) {
        exercise = testing; outputRoot = output;
        Text = "LocalScribe NPU 0.5.0 — 時間制限付き同梱候補";
        ClientSize = new Size(900, 610); MinimumSize = new Size(820, 580);
        Font = new Font("Yu Gothic UI", 10); AutoScaleMode = AutoScaleMode.Dpi;
        var layout = new TableLayoutPanel { Dock=DockStyle.Fill, Padding=new Padding(16), ColumnCount=1, RowCount=6 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,44));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,64));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,38));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,48));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute,64));
        var title = new Label { Text="LocalScribe NPU — 音声ファイル文字起こし", AutoSize=true, Font=new Font(Font.FontFamily,16,FontStyle.Bold), Dock=DockStyle.Fill };
        layout.Controls.Add(title);
        note.Text="NPU動作確認用の同梱候補です。ライブ録音はまだありません。\r\nNPU：全体15分で打切り。中止は認識処理の終了を待たずに実行します。";
        note.Dock=DockStyle.Fill; layout.Controls.Add(note);
        audio.Dock=DockStyle.Fill; layout.Controls.Add(audio);
        var row = new FlowLayoutPanel { Dock=DockStyle.Fill, WrapContents=false };
        choose.Text="音声を選択"; choose.AutoSize=true;
        choose.Click += delegate { using(var dialog = new OpenFileDialog { Filter="WAV / FLAC|*.wav;*.flac", CheckFileExists=true }) if(dialog.ShowDialog(this)==DialogResult.OK) audio.Text=dialog.FileName; };
        device.DropDownStyle=ComboBoxStyle.DropDownList; device.Items.AddRange(new object[]{"NPU","CPU","GPU"}); device.SelectedIndex=0; device.Width=80;
        start.Text="開始"; start.AutoSize=true; start.Click += delegate { if(!busy) ActiveTask=Run(); };
        cancel.Text="中止"; cancel.Enabled=false; cancel.AutoSize=true; cancel.Click += delegate { cancellation="cancelled"; status.Text="中止処理中…"; };
        folder.Text="保存先を開く"; folder.AutoSize=true;
        folder.Click += delegate { try { if(Directory.Exists(outputRoot)) Process.Start(new ProcessStartInfo(outputRoot){UseShellExecute=true}); } catch(Exception ex) {status.Text=ex.Message;} };
        row.Controls.AddRange(new Control[]{choose,device,start,cancel,folder}); layout.Controls.Add(row);
        display.Multiline=true; display.ReadOnly=true; display.ScrollBars=ScrollBars.Vertical; display.Dock=DockStyle.Fill; layout.Controls.Add(display);
        status.Text="0.1〜30秒のWAV／FLACを選択してください。\r\n保存先："+outputRoot; status.Dock=DockStyle.Fill; layout.Controls.Add(status);
        Controls.Add(layout);
        heartbeat.Interval=50; heartbeat.Tick += delegate {
            double now=uiClock.Elapsed.TotalSeconds;
            if(shown && now-lastTick>maxGap) {maxGap=now-lastTick;maxGapPhase=phase;}
            lastTick=now;
        };
        Shown += delegate {startupSeconds=uiClock.Elapsed.TotalSeconds;lastTick=startupSeconds;shown=true;heartbeat.Start();};
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if(busy) { e.Cancel=true; closeRequested=true; cancellation="cancelled"; } };
    }
    static JavaScriptSerializer Serializer() { return new JavaScriptSerializer { MaxJsonLength=262144 }; }
    static string Json(object value) { return Serializer().Serialize(value); }
    static string Get(Dictionary<string,object> d,string key) { return d.ContainsKey(key)?Convert.ToString(d[key],System.Globalization.CultureInfo.InvariantCulture):""; }
    static void Atomic(string path,string body) {
        string temp=path+"."+Guid.NewGuid().ToString("N")+".tmp";
        byte[] data=new UTF8Encoding(false).GetBytes(body);
        try {
            using(var f=new FileStream(temp,FileMode.CreateNew,FileAccess.Write,FileShare.Read)) { f.Write(data,0,data.Length); f.Flush(true); }
            if(File.Exists(path)) File.Replace(temp,path,null); else File.Move(temp,path);
        } finally { if(File.Exists(temp)) {try{File.Delete(temp);}catch(IOException){}} }
    }
    static string Hash(string path) { using(var s=SHA256.Create())using(var f=File.OpenRead(path)) return BitConverter.ToString(s.ComputeHash(f)).Replace("-","").ToLowerInvariant(); }
    void Enable(bool enabled) { start.Enabled=choose.Enabled=device.Enabled=audio.Enabled=enabled; cancel.Enabled=!enabled; }
    void SetPhase(string next) { phase=next; if(PhaseSeen!=null) PhaseSeen(next); }
    string PublicError(Exception ex) {
        string text=ex.GetType().Name+": "+ex.Message;
        foreach(string path in new[]{audio.Text,activeDir,baseDir,Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)})
            if(!String.IsNullOrEmpty(path)) text=text.Replace(path,"[local-path]");
        return text.Length>3000?text.Substring(0,3000):text;
    }
    async Task<string> ReadBounded(StreamReader reader, bool protocol) {
        var buffer=new StringBuilder(); char[] chars=new char[2048]; int total=0, count;
        while((count=await reader.ReadAsync(chars,0,chars.Length))>0) {
            total+=count; if(total>262144) throw new IOException("WORKER_OUTPUT_LIMIT");
            buffer.Append(chars,0,count);
            if(protocol) {
                int newline;
                while((newline=buffer.ToString().IndexOf('\n'))>=0) {
                    string line=buffer.ToString(0,newline).TrimEnd('\r'); buffer.Remove(0,newline+1);
                    if(!line.StartsWith("LSJSON:")) continue;
                    var message=Serializer().Deserialize<Dictionary<string,object>>(line.Substring(7));
                    if(Get(message,"event")=="phase") SetPhase(Get(message,"phase"));
                    else if(Get(message,"event")=="result") {
                        if(Last!=null) throw new IOException("DUPLICATE_RESULT");
                        Last=message;
                    }
                }
            }
        }
        return buffer.ToString();
    }
    async Task StopOwnedChild() {
        if(child==null) return;
        try { if(!child.HasExited) child.Kill(); } catch(InvalidOperationException) { return; }
        var wait=Stopwatch.StartNew();
        while(!child.HasExited && wait.Elapsed.TotalSeconds<3) await Task.Delay(25);
        if(!child.HasExited) throw new IOException("WORKER_STOP_NOT_CONFIRMED");
    }
    async Task<Dictionary<string,object>> Run() {
        busy=true; cancellation=null; Last=null; activeDir=null; Enable(false); phase="preflight";
        var clock=Stopwatch.StartNew();
        var record=new Dictionary<string,object>{{"version",Version},{"outcome","running"},{"phase",phase},{"npu_components_verified",false},{"live_tested",false}};
        string text=""; Task<string> stdout=null, stderr=null;
        try {
            string selected=Path.GetFullPath(audio.Text);
            if(!File.Exists(selected)) throw new FileNotFoundException("Select an existing local audio file");
            string chosen=Convert.ToString(device.SelectedItem);
            double limit=exercise && testLimit>0?testLimit:(chosen=="CPU"?120:900);
            record["requested_device"]=chosen; record["timeout_seconds"]=limit;
            Directory.CreateDirectory(outputRoot);
            activeDir=Path.Combine(outputRoot,DateTime.Now.ToString("yyyyMMdd_HHmmss_")+Guid.NewGuid().ToString("N").Substring(0,8));
            Directory.CreateDirectory(activeDir);
            Atomic(Path.Combine(activeDir,"result.md"),"# LocalScribe\n\n状態: 処理中。これだけでは成功を意味しません。\n");
            string executable=Path.Combine(baseDir,"worker","WhisperWorker.exe");
            string manifest=Path.Combine(baseDir,"worker.sha256");
            if(!File.Exists(executable)||!File.Exists(manifest)) throw new IOException("Bundled worker is missing");
            string expected=File.ReadAllText(manifest).Trim();
            string actual=await Task.Run(()=>Hash(executable));
            if(actual!=expected) throw new IOException("WORKER_HASH_MISMATCH");
            if(cancellation!=null) throw new OperationCanceledException();
            var info=new ProcessStartInfo(executable) { WorkingDirectory=Path.GetDirectoryName(executable),UseShellExecute=false,CreateNoWindow=true,
                RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true, StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8 };
            info.EnvironmentVariables["PYTHONUTF8"]="1"; info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
            info.EnvironmentVariables["HF_HUB_OFFLINE"]="1"; info.EnvironmentVariables["HF_HUB_DISABLE_TELEMETRY"]="1";
            job=new OwnedJob(); child=new Process { StartInfo=info };
            await Task.Run(delegate {
                if(!child.Start()) throw new IOException("Worker did not start");
                job.Attach(child);
            });
            stdout=ReadBounded(child.StandardOutput,true); stderr=ReadBounded(child.StandardError,false);
            string request=String.Concat(Json(new {audio=selected,device=chosen,@case=exercise?testCase:"normal",developer_exercise=exercise}).Select(c=>c>127 ? "\\u"+((int)c).ToString("x4") : c.ToString()));
            await child.StandardInput.WriteAsync(request); child.StandardInput.Close();
            while(!child.HasExited) {
                if(stdout.IsFaulted||stderr.IsFaulted) throw new IOException("Worker output protocol failed");
                if(cancellation==null && clock.Elapsed.TotalSeconds>=limit) cancellation="timed_out";
                if(cancellation!=null) { await StopOwnedChild(); break; }
                status.Text="処理中："+phase+"　経過 "+clock.Elapsed.TotalSeconds.ToString("F0")+" / 上限 "+limit.ToString("F0")+" 秒";
                await Task.Delay(50);
            }
            var pipes=Task.WhenAll(stdout,stderr);
            if(await Task.WhenAny(pipes,Task.Delay(2000))!=pipes) throw new IOException("Worker pipes did not close");
            await pipes;
            if(child.ExitCode!=0 && Last==null) {
                string detail=stderr.Result;
                foreach(string p in new[]{selected,activeDir,baseDir,Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)})
                    if(!String.IsNullOrEmpty(p)) detail=detail.Replace(p,"[local-path]");
                record["worker_error_detail"]=detail.Length>4000?detail.Substring(detail.Length-4000):detail;
            }
            record["exit_code"]=child.ExitCode; record["worker_exit_confirmed"]=child.HasExited;
            if(cancellation!=null) {record["outcome"]=cancellation; record["phase"]=phase;}
            else if(Last==null) throw new IOException("WORKER_EXIT_WITHOUT_RESULT: "+child.ExitCode);
            else {
                foreach(var pair in Last) if(pair.Key!="text" && pair.Key!="event") record[pair.Key]=pair.Value;
                if(Get(record,"outcome")=="success") {
                    if(child.ExitCode!=0) throw new IOException("Worker reported success but exit was nonzero");
                    text=Get(Last,"text");
                    if(String.IsNullOrWhiteSpace(text)||text.Length>16000) throw new IOException("Invalid transcript");
                    phase="transcript_save";
                    string body="# 文字起こし\n\n> 自動認識・人手未確認。入力元・人物の自動識別は未実装。\n\n"+text+"\n";
                    Atomic(Path.Combine(activeDir,"transcript.md"),body);
                    if(File.ReadAllText(Path.Combine(activeDir,"transcript.md"),Encoding.UTF8)!=body) throw new IOException("TRANSCRIPT_READBACK_MISMATCH");
                    text=body; record["phase"]="complete";
                }
            }
        } catch(OperationCanceledException) { record["outcome"]="cancelled"; record["phase"]=phase; }
        catch(Exception ex) {record["outcome"]="failed"; record["phase"]=phase; record["error"]=PublicError(ex);}
        {
            try {await StopOwnedChild();} catch(Exception ex) {record["stop_error"]=PublicError(ex); record["outcome"]="failed";}
            if(job!=null) {job.Dispose();job=null;}
            if(child!=null) {child.Dispose();child=null;}
        }
        record["elapsed_seconds"]=Math.Round(clock.Elapsed.TotalSeconds,3);
        try {
            if(activeDir==null) throw new IOException("Output directory not created");
            Atomic(Path.Combine(activeDir,"state.json"),Json(record));
            var body=new StringBuilder("# LocalScribe — 実行結果\n\n> NPU各部の実行先・ライブ入力・一般精度は未検証。\n\n");
            foreach(var pair in record) body.Append("- "+pair.Key+": `"+Json(pair.Value).Replace("`","'")+"`\n");
            body.Append("\n音声原本は変更していません。本文は transcript.md に別保存。共有前に内容を確認してください。\n");
            Atomic(Path.Combine(activeDir,"result.md"),body.ToString());
        } catch(Exception ex) {record["report_save_error"]=PublicError(ex); record["outcome"]="failed";
            try {if(activeDir!=null) Atomic(Path.Combine(activeDir,"state.json"),Json(record));} catch(Exception) {}
        }
        Last=record; busy=false; Enable(true);
        display.Text=Get(record,"outcome")=="success"?text:Json(record);
        status.Text="結果："+Get(record,"outcome")+"\r\n保存先："+(activeDir??outputRoot);
        if(closeRequested) Close();
        return record;
    }

    public async Task Exercise(string fixture,string evidence) {
        var rows=new List<object>(); string original=Hash(fixture); var saved=new Dictionary<string,string>();
        try {
            Directory.CreateDirectory(evidence);
            await Task.Delay(100);
            string silence=Path.Combine(Path.GetDirectoryName(fixture),"silence.wav");
            string modelFile=Path.Combine(baseDir,"worker","models","config.json");
            foreach(string test in new[]{"normal","stereo_48khz","timeout_native","cancel_native","early_exit","save_obstruction","missing_model","silence","unavailable_npu","recovery"}) {
                audio.Text=test=="silence"?silence:(test=="stereo_48khz"?Path.Combine(Path.GetDirectoryName(fixture),"stereo.wav"):fixture);
                device.SelectedItem=test=="unavailable_npu"?"NPU":"CPU";
                testCase=(test=="timeout_native"||test=="cancel_native")?"native_wait":(test=="early_exit"?"early_exit":"normal");
                testLimit=test=="timeout_native"?2:120;
                bool obstruct=test=="save_obstruction";
                PhaseSeen=delegate(string p) {
                    if(test=="cancel_native"&&p=="native_wait") cancel.PerformClick();
                    if(obstruct&&p=="transcribe_1") Directory.CreateDirectory(Path.Combine(activeDir,"transcript.md"));
                };
                if(test=="missing_model") File.Move(modelFile,modelFile+".hold");
                try {start.PerformClick(); await ActiveTask;}
                finally {if(test=="missing_model") File.Move(modelFile+".hold",modelFile);}
                string expected=test=="timeout_native"?"timed_out":test=="cancel_native"?"cancelled":(test=="normal"||test=="stereo_48khz"||test=="recovery"?"success":"failed");
                if(Get(Last,"outcome")!=expected) throw new Exception(test+" wrong outcome: "+Json(Last));
                if((test=="timeout_native"||test=="cancel_native") && Get(Last,"phase")!="native_wait") throw new Exception("Native-wait phase not reached");
                if(test=="timeout_native" && Convert.ToDouble(Last["elapsed_seconds"])>7) throw new Exception("Timeout exceeded bounded margin");
                if(test=="cancel_native" && Convert.ToDouble(Last["elapsed_seconds"])>8) throw new Exception("Cancellation exceeded bounded margin");
                if(expected=="success") {
                    string target=Path.Combine(activeDir,"transcript.md");
                    if(!display.Text.Contains("マレーシア")||display.Text!=File.ReadAllText(target,Encoding.UTF8)) throw new Exception("GUI/output mismatch");
                    saved[target]=Hash(target);
                } else if(File.Exists(Path.Combine(activeDir,"transcript.md"))) throw new Exception("Failed result accepted as transcript");
                rows.Add(new {name=test,outcome=Get(Last,"outcome"),phase=Get(Last,"phase"),elapsed=Last["elapsed_seconds"],worker_exit=Get(Last,"worker_exit_confirmed")});
            }
            if(Hash(fixture)!=original||saved.Any(p=>Hash(p.Key)!=p.Value)) throw new Exception("Existing input/output changed");
            if(startupSeconds>10) throw new Exception("Window startup exceeded ten seconds: "+startupSeconds);
            if(maxGap>1.5) throw new Exception("UI event loop blocked: "+maxGap+" phase="+maxGapPhase);
            Atomic(Path.Combine(evidence,"native-gui.json"),Json(new {outcome="passed",cases=rows,visible=Visible,maximum_ui_gap=maxGap,maximum_ui_gap_phase=maxGapPhase,creation_to_shown_seconds=startupSeconds,input_preserved=true,accepted_outputs_preserved=true,npu_tested=false,live_tested=false}));
            Environment.ExitCode=0;
        } catch(Exception ex) {
            Atomic(Path.Combine(evidence,"native-gui.json"),Json(new {outcome="failed",error=ex.ToString(),cases=rows,maximum_ui_gap=maxGap,maximum_ui_gap_phase=maxGapPhase,creation_to_shown_seconds=startupSeconds})); Environment.ExitCode=1;
        } finally {PhaseSeen=null;Close();}
    }
    [STAThread] static int Main(string[] args) {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        bool exercise=args.Length==3 && args[0]=="--exercise";
        string output=exercise?Path.Combine(args[2],"private-output"):Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"LocalScribeNPU");
        var form=new Host(output,exercise);
        if(exercise) form.Shown += async delegate {await form.Exercise(args[1],args[2]);};
        Application.Run(form); return Environment.ExitCode;
    }
}
