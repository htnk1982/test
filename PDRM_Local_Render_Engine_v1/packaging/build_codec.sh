#!/usr/bin/env bash
# Build an audio-only, network-disabled LGPL FFmpeg. Ship exact sources/recipe.
set -euo pipefail
ROOT="$(pwd)/codec-build"
PREFIX="$ROOT/prefix"
OUT="$(pwd)/codec-dist"
mkdir -p "$ROOT" "$PREFIX" "$OUT/SOURCES" "$OUT/LICENSES"
trap 'tail -n 60 "$OUT"/*configure.log "$OUT"/*build.log 2>/dev/null || true' ERR
curl -fL --retry 3 https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz -o "$OUT/SOURCES/ffmpeg-7.1.5.tar.xz"
curl -fL --retry 3 https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz -o "$OUT/SOURCES/lame-3.100.tar.gz"
cp "$0" "$OUT/SOURCES/build_codec.sh"
cd "$ROOT"
tar -xf "$OUT/SOURCES/lame-3.100.tar.gz"
cd lame-3.100
./configure --host=x86_64-w64-mingw32 --prefix="$PREFIX" --disable-shared --enable-static --disable-decoder --disable-frontend --disable-asm CFLAGS='-O2 -fcommon' > "$OUT/lame-configure.log" 2>&1
make -j2 > "$OUT/lame-build.log" 2>&1
make install >> "$OUT/lame-build.log" 2>&1
cp COPYING "$OUT/LICENSES/LAME-LGPL.txt"
cd "$ROOT"
tar -xf "$OUT/SOURCES/ffmpeg-7.1.5.tar.xz"
cd ffmpeg-7.1.5
./configure --prefix="$PREFIX" --enable-cross-compile --target-os=mingw32 --arch=x86_64 \
 --cross-prefix=x86_64-w64-mingw32- --pkg-config=pkg-config --pkg-config-flags=--static \
 --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib -static" \
 --disable-everything --disable-autodetect --disable-shared --enable-static \
 --disable-debug --disable-doc --disable-x86asm --disable-programs --enable-ffmpeg \
 --disable-network --disable-avdevice --disable-swscale --disable-postproc \
 --enable-avfilter --enable-swresample --enable-libmp3lame \
 --enable-protocol=file,pipe --enable-demuxer=wav,mp3,flac \
 --enable-muxer=wav,mp3,null --enable-parser=mpegaudio,flac \
 --enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,mp3,mp3float,flac \
 --enable-encoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,libmp3lame \
 --enable-filter=abuffer,abuffersink,aformat,anull,aresample,alimiter,volume,asetpts,atrim \
 > "$OUT/ffmpeg-configure.log" 2>&1
make -j2 > "$OUT/ffmpeg-build.log" 2>&1
cp ffmpeg.exe "$OUT/ffmpeg.exe"
cp COPYING.LGPLv2.1 "$OUT/LICENSES/FFmpeg-LGPLv2.1.txt"
cp LICENSE.md "$OUT/LICENSES/FFmpeg-LICENSE.md"
cp ffbuild/config.log "$OUT/SOURCES/ffmpeg-config.log"
x86_64-w64-mingw32-gcc --version > "$OUT/SOURCES/compiler-version.txt"
x86_64-w64-mingw32-objdump -p "$OUT/ffmpeg.exe" > "$OUT/ffmpeg-pe-imports.txt"
for file in /usr/share/doc/mingw-w64-common/copyright /usr/share/doc/gcc-mingw-w64-x86-64-posix/copyright; do
 if test -f "$file"; then cp "$file" "$OUT/LICENSES/$(basename "$(dirname "$file")")-copyright.txt"; fi
done
cd "$OUT"
sha256sum ffmpeg.exe SOURCES/*.tar.* > SHA256SUMS.txt
