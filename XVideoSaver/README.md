# X Video Saver

個人利用向けの小型Androidアプリです。Xアプリから公開投稿を共有し、投稿に含まれるMP4動画のうち最も高品質な候補を端末へ保存します。

## 使い方

1. Xアプリで動画付き投稿を開く
2. ［共有］をタップ
3. ［X Video Saver］を選ぶ
4. ［最高画質で保存］をタップ
5. Android 10以降では `Download/XVideoSaver/` に保存

URLを直接貼り付けることもできます。

## 仕様

- Android 7.0（API 24）以上
- X / twitter.com の公開投稿URLに対応
- 最高品質のMP4候補を選択
- Android 10以降はMediaStore経由でDownloadフォルダへ保存
- Android 7〜9はAndroid標準の保存先選択画面を使用
- ストレージ権限は要求しない
- ログイン情報・Cookie・X APIキーは保持しない
- 広告・解析SDKなし

## 制約

XのSyndication（埋め込み）用エンドポイントは公開APIとして保証されたものではありません。そのため、X側の仕様変更で取得できなくなる可能性があります。また、センシティブ指定、非公開、ログイン必須、削除済みなどの投稿は取得できない場合があります。

保存した動画の利用・再配布は、権利者の権利とXの利用条件に従ってください。

## ビルド

Android Gradle Plugin 8.8.2 / Gradle 8.10.2 / Java 17 / compileSdk 35 を想定しています。

```bash
gradle :app:assembleDebug
```

生成物: `app/build/outputs/apk/debug/app-debug.apk`
