package jp.local.xvideosaver;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final int REQUEST_CREATE_DOCUMENT = 2001;
    private static final Pattern STATUS_ID_PATTERN = Pattern.compile(
            "(?:https?://)?(?:www\\.)?(?:x\\.com|twitter\\.com)/[^\\s/]+/status/(\\d+)",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern RESOLUTION_PATTERN = Pattern.compile("/(\\d{2,5})x(\\d{2,5})/");

    private EditText urlInput;
    private Button saveButton;
    private Button pasteButton;
    private TextView statusView;
    private ProgressBar progressBar;

    private String pendingVideoUrl;
    private String pendingTweetId;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        acceptIncomingIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        acceptIncomingIntent(intent);
    }

    private void buildUi() {
        int pad = dp(20);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        root.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView title = new TextView(this);
        title.setText("X Video Saver");
        title.setTextSize(26f);
        title.setGravity(Gravity.CENTER);
        root.addView(title, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        TextView subtitle = new TextView(this);
        subtitle.setText("Xの公開動画を最高画質のMP4で保存します。\nXアプリの［共有］からこのアプリを選ぶのが最短です。");
        subtitle.setTextSize(15f);
        subtitle.setPadding(0, dp(12), 0, dp(18));
        root.addView(subtitle, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        urlInput = new EditText(this);
        urlInput.setHint("https://x.com/.../status/...");
        urlInput.setSingleLine(false);
        urlInput.setMinLines(2);
        urlInput.setMaxLines(4);
        urlInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        root.addView(urlInput, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setPadding(0, dp(12), 0, 0);

        pasteButton = new Button(this);
        pasteButton.setText("貼り付け");
        pasteButton.setOnClickListener(v -> pasteFromClipboard());
        buttons.addView(pasteButton, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));

        saveButton = new Button(this);
        saveButton.setText("最高画質で保存");
        saveButton.setOnClickListener(v -> beginResolve());
        LinearLayout.LayoutParams saveLp = new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 2f);
        saveLp.setMarginStart(dp(8));
        buttons.addView(saveButton, saveLp);

        root.addView(buttons, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(1000);
        progressBar.setProgress(0);
        progressBar.setVisibility(View.GONE);
        LinearLayout.LayoutParams progressLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(12));
        progressLp.setMargins(0, dp(18), 0, dp(8));
        root.addView(progressBar, progressLp);

        statusView = new TextView(this);
        statusView.setText("待機中");
        statusView.setTextSize(14f);
        root.addView(statusView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        TextView note = new TextView(this);
        note.setText("対象: 公開されているX動画。センシティブ指定・非公開・ログイン必須の投稿は取得できない場合があります。保存した動画の利用・再配布は権利者とXの条件に従ってください。");
        note.setTextSize(12f);
        note.setPadding(0, dp(24), 0, 0);
        root.addView(note, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        setContentView(root);
    }

    private void acceptIncomingIntent(Intent intent) {
        if (intent == null) return;
        if (Intent.ACTION_SEND.equals(intent.getAction()) && "text/plain".equals(intent.getType())) {
            String shared = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (shared != null) {
                Matcher m = STATUS_ID_PATTERN.matcher(shared);
                if (m.find()) {
                    String matchedUrl = m.group(0);
                    urlInput.setText(matchedUrl);
                    urlInput.setSelection(matchedUrl.length());
                    statusView.setText("共有されたX投稿を受け取りました。［最高画質で保存］を押してください。");
                }
            }
        }
    }

    private void pasteFromClipboard() {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        if (clipboard == null || !clipboard.hasPrimaryClip()) {
            Toast.makeText(this, "クリップボードに文字列がありません", Toast.LENGTH_SHORT).show();
            return;
        }
        ClipData clip = clipboard.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) return;
        CharSequence text = clip.getItemAt(0).coerceToText(this);
        if (text != null) {
            urlInput.setText(text.toString());
            urlInput.setSelection(urlInput.length());
        }
    }

    private void beginResolve() {
        String raw = urlInput.getText().toString().trim();
        Matcher matcher = STATUS_ID_PATTERN.matcher(raw);
        if (!matcher.find()) {
            setError("Xの投稿URLを認識できません。/status/数字 を含むURLを貼り付けてください。");
            return;
        }

        String tweetId = matcher.group(1);
        setBusy(true);
        progressBar.setVisibility(View.VISIBLE);
        progressBar.setIndeterminate(true);
        statusView.setText("動画情報を取得中…");

        new Thread(() -> {
            try {
                Candidate candidate = resolveBestMp4(tweetId);
                runOnUiThread(() -> {
                    pendingVideoUrl = candidate.url;
                    pendingTweetId = tweetId;
                    statusView.setText(candidate.label + " を取得しました。保存を開始します…");
                    saveResolvedVideo();
                });
            } catch (Exception e) {
                runOnUiThread(() -> setError(userFriendlyError(e)));
            }
        }, "x-video-resolver").start();
    }

    private Candidate resolveBestMp4(String tweetId) throws Exception {
        // The syndication endpoint is used by X/Twitter embed infrastructure. It is undocumented,
        // so try several currently accepted token forms before treating the post as unavailable.
        String[] tokens = {"x", "0", "a"};
        Exception last = null;

        for (String token : tokens) {
            try {
                String endpoint = "https://cdn.syndication.twimg.com/tweet-result?id="
                        + tweetId + "&lang=ja&token=" + token;
                String json = getText(endpoint);
                if (json == null || json.trim().isEmpty() || "{}".equals(json.trim())) {
                    continue;
                }

                JSONObject root = new JSONObject(json);
                List<Candidate> candidates = new ArrayList<>();
                collectCandidates(root, candidates);
                if (!candidates.isEmpty()) {
                    Candidate best = candidates.get(0);
                    for (Candidate c : candidates) {
                        if (c.score > best.score) best = c;
                    }
                    return best;
                }
            } catch (Exception e) {
                last = e;
            }
        }

        if (last != null && !(last instanceof JSONException)) {
            throw last;
        }
        throw new IOException("NO_PUBLIC_MP4");
    }

    private String getText(String endpoint) throws IOException {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(endpoint).openConnection();
            conn.setInstanceFollowRedirects(true);
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(20000);
            conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36");
            conn.setRequestProperty("Accept", "application/json,text/plain,*/*");
            conn.setRequestProperty("Referer", "https://platform.twitter.com/");

            int code = conn.getResponseCode();
            InputStream stream = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            String body = stream == null ? "" : readAll(stream, 3 * 1024 * 1024);
            if (code < 200 || code >= 300) {
                throw new IOException("SYNDICATION_HTTP_" + code + (body.isEmpty() ? "" : ": " + body));
            }
            return body;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private String readAll(InputStream input, int maxBytes) throws IOException {
        try (InputStream in = input; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int total = 0;
            int n;
            while ((n = in.read(buf)) != -1) {
                total += n;
                if (total > maxBytes) throw new IOException("RESPONSE_TOO_LARGE");
                out.write(buf, 0, n);
            }
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }

    private void collectCandidates(Object node, List<Candidate> out) throws JSONException {
        if (node instanceof JSONObject) {
            JSONObject obj = (JSONObject) node;

            JSONArray variants = obj.optJSONArray("variants");
            if (variants != null) {
                for (int i = 0; i < variants.length(); i++) {
                    JSONObject variant = variants.optJSONObject(i);
                    if (variant != null) addVariant(variant, i, out);
                }
            }

            Iterator<String> keys = obj.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                Object child = obj.opt(key);
                if (child instanceof JSONObject || child instanceof JSONArray) {
                    collectCandidates(child, out);
                }
            }
        } else if (node instanceof JSONArray) {
            JSONArray array = (JSONArray) node;
            for (int i = 0; i < array.length(); i++) {
                Object child = array.opt(i);
                if (child instanceof JSONObject || child instanceof JSONArray) {
                    collectCandidates(child, out);
                }
            }
        }
    }

    private void addVariant(JSONObject variant, int order, List<Candidate> out) {
        String mime = variant.optString("content_type", variant.optString("type", ""));
        String url = variant.optString("url", variant.optString("src", ""));
        if (url.isEmpty()) return;

        boolean mp4 = "video/mp4".equalsIgnoreCase(mime)
                || url.toLowerCase(Locale.ROOT).contains(".mp4");
        if (!mp4) return;

        Uri parsed = Uri.parse(url);
        String host = parsed.getHost();
        if (!"https".equalsIgnoreCase(parsed.getScheme()) || host == null) return;
        String lowerHost = host.toLowerCase(Locale.ROOT);
        if (!("video.twimg.com".equals(lowerHost) || lowerHost.endsWith(".twimg.com"))) return;

        long bitrate = variant.optLong("bitrate", 0L);
        long score = bitrate > 0 ? bitrate * 1000L : 0L;
        String resolution = "MP4";

        Matcher resolutionMatcher = RESOLUTION_PATTERN.matcher(url);
        if (resolutionMatcher.find()) {
            try {
                long w = Long.parseLong(resolutionMatcher.group(1));
                long h = Long.parseLong(resolutionMatcher.group(2));
                if (score == 0) score = w * h;
                resolution = w + "×" + h + " MP4";
            } catch (NumberFormatException ignored) {
                // Keep generic label.
            }
        }

        if (score == 0) score = order + 1L;
        out.add(new Candidate(url, score, resolution));
    }

    private void saveResolvedVideo() {
        if (pendingVideoUrl == null || pendingTweetId == null) {
            setError("内部状態を復元できませんでした。もう一度実行してください。");
            return;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            saveWithMediaStore();
        } else {
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("video/mp4");
            intent.putExtra(Intent.EXTRA_TITLE, fileName());
            startActivityForResult(intent, REQUEST_CREATE_DOCUMENT);
        }
    }

    private void saveWithMediaStore() {
        ContentResolver resolver = getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, fileName());
        values.put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4");
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/XVideoSaver");
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);

        Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (uri == null) {
            setError("Downloadフォルダに保存先を作成できませんでした。");
            return;
        }

        downloadInto(uri, true);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_CREATE_DOCUMENT) return;

        if (resultCode == RESULT_OK && data != null && data.getData() != null) {
            downloadInto(data.getData(), false);
        } else {
            statusView.setText("保存をキャンセルしました。");
            setBusy(false);
            progressBar.setVisibility(View.GONE);
        }
    }

    private void downloadInto(Uri destination, boolean mediaStorePending) {
        progressBar.setVisibility(View.VISIBLE);
        progressBar.setIndeterminate(true);
        statusView.setText("動画をダウンロード中…");

        final String sourceUrl = pendingVideoUrl;
        new Thread(() -> {
            HttpURLConnection conn = null;
            boolean success = false;
            try {
                conn = (HttpURLConnection) new URL(sourceUrl).openConnection();
                conn.setInstanceFollowRedirects(true);
                conn.setConnectTimeout(20000);
                conn.setReadTimeout(30000);
                conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36");
                conn.setRequestProperty("Accept", "video/mp4,*/*");

                int code = conn.getResponseCode();
                if (code < 200 || code >= 300) {
                    throw new IOException("VIDEO_HTTP_" + code);
                }

                long total = conn.getContentLengthLong();
                ContentResolver resolver = getContentResolver();
                try (InputStream rawIn = conn.getInputStream();
                     BufferedInputStream in = new BufferedInputStream(rawIn, 64 * 1024);
                     OutputStream rawOut = resolver.openOutputStream(destination, "w")) {

                    if (rawOut == null) throw new IOException("OUTPUT_STREAM_NULL");
                    try (BufferedOutputStream out = new BufferedOutputStream(rawOut, 64 * 1024)) {
                        byte[] buffer = new byte[64 * 1024];
                        long done = 0;
                        long lastUi = 0;
                        int n;
                        while ((n = in.read(buffer)) != -1) {
                            out.write(buffer, 0, n);
                            done += n;
                            long now = System.currentTimeMillis();
                            if (now - lastUi >= 250) {
                                lastUi = now;
                                postProgress(done, total);
                            }
                        }
                        out.flush();
                        postProgress(done, total);
                    }
                }

                if (mediaStorePending && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    ContentValues doneValues = new ContentValues();
                    doneValues.put(MediaStore.MediaColumns.IS_PENDING, 0);
                    resolver.update(destination, doneValues, null, null);
                }
                success = true;

                runOnUiThread(() -> {
                    progressBar.setIndeterminate(false);
                    progressBar.setProgress(1000);
                    statusView.setText("保存完了: Download/XVideoSaver/" + fileName());
                    setBusy(false);
                    Toast.makeText(this, "動画を保存しました", Toast.LENGTH_LONG).show();
                });
            } catch (Exception e) {
                if (mediaStorePending) {
                    try {
                        getContentResolver().delete(destination, null, null);
                    } catch (Exception ignored) {
                    }
                }
                runOnUiThread(() -> setError(userFriendlyError(e)));
            } finally {
                if (conn != null) conn.disconnect();
                if (!success && !mediaStorePending) {
                    // For user-selected documents Android owns cleanup semantics.
                }
            }
        }, "x-video-download").start();
    }

    private void postProgress(long done, long total) {
        runOnUiThread(() -> {
            if (total > 0) {
                progressBar.setIndeterminate(false);
                int value = (int) Math.min(1000L, (done * 1000L) / total);
                progressBar.setProgress(value);
                statusView.setText(String.format(Locale.JAPAN,
                        "ダウンロード中… %.1f / %.1f MB (%d%%)",
                        done / 1048576.0,
                        total / 1048576.0,
                        value / 10));
            } else {
                progressBar.setIndeterminate(true);
                statusView.setText(String.format(Locale.JAPAN,
                        "ダウンロード中… %.1f MB", done / 1048576.0));
            }
        });
    }

    private String fileName() {
        String id = pendingTweetId == null ? "video" : pendingTweetId;
        return "X_" + id + ".mp4";
    }

    private void setBusy(boolean busy) {
        saveButton.setEnabled(!busy);
        pasteButton.setEnabled(!busy);
        urlInput.setEnabled(!busy);
    }

    private void setError(String message) {
        progressBar.setVisibility(View.GONE);
        progressBar.setIndeterminate(false);
        progressBar.setProgress(0);
        statusView.setText("エラー: " + message);
        setBusy(false);
    }

    private String userFriendlyError(Throwable error) {
        String message = error.getMessage() == null ? "" : error.getMessage();
        if (message.contains("NO_PUBLIC_MP4") || message.contains("SYNDICATION_HTTP_404")) {
            return "公開MP4を取得できませんでした。センシティブ指定、非公開、ログイン必須、削除済み、またはX側の仕様変更が考えられます。";
        }
        if (message.contains("SYNDICATION_HTTP_429")) {
            return "X側で一時的にアクセス制限されています。少し時間を置いて再実行してください。";
        }
        if (message.contains("VIDEO_HTTP_403")) {
            return "動画URLへのアクセスが拒否されました。X側でURLが更新された可能性があります。もう一度投稿URLから実行してください。";
        }
        if (error instanceof java.net.SocketTimeoutException) {
            return "通信がタイムアウトしました。回線を確認して再実行してください。";
        }
        if (error instanceof IOException) {
            return "通信または保存に失敗しました。" + (message.isEmpty() ? "" : " (" + message + ")");
        }
        return message.isEmpty() ? error.getClass().getSimpleName() : message;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class Candidate {
        final String url;
        final long score;
        final String label;

        Candidate(String url, long score, String label) {
            this.url = url;
            this.score = score;
            this.label = label;
        }
    }
}
