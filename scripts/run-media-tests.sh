#!/usr/bin/env bash
set -euo pipefail
test_root="$(cd "$(dirname "$0")" && pwd)"
ffmpeg -v error -f lavfi -i testsrc2=size=320x240:rate=30 \
    -f lavfi -i sine=frequency=440:sample_rate=48000 -t 1 \
    -c:v libx264 -threads 1 -c:a pcm_s16le /tmp/av-test.mkv
ffmpeg -v error -i /tmp/av-test.mkv -an -c:v copy /tmp/video-test.mp4
cp /tmp/video-test.mp4 /tmp/video-only.mp4
printf invalid > /tmp/invalid.mp4
g++ -std=c++11 -pthread -I/app/demo -I/app/demo/include/h \
    "$test_root/video-source-test.cpp" /app/demo/ZoomSDKVideoSource.cpp -o /tmp/video-source-test
g++ -std=c++11 -pthread -I/app/demo -I/app/demo/include/h \
    "$test_root/av-source-test.cpp" /app/demo/ZoomSDKVideoSource.cpp \
    /app/demo/ZoomSDKVirtualAudioMicEvent.cpp -o /tmp/av-source-test
g++ -std=c++11 -pthread -I/app/demo -I/app/demo/include/h \
    "$test_root/error-handling-test.cpp" /app/demo/AuthServiceEventListener.cpp \
    /app/demo/MeetingServiceEventListener.cpp -o /tmp/error-handling-test
timeout 20 /tmp/video-source-test
timeout 20 /tmp/av-source-test
timeout 20 /tmp/error-handling-test
g++ -std=c++11 -pthread -I/app/demo -I/app/demo/include/h \
    "$test_root/playback-control-test.cpp" /app/demo/ZoomSDKVideoSource.cpp \
    /app/demo/ZoomSDKVirtualAudioMicEvent.cpp -o /tmp/playback-control-test
timeout 20 /tmp/playback-control-test
g++ -std=c++11 -pthread -I/app/demo $(pkg-config --cflags gio-2.0 json-glib-1.0) \
    "$test_root/sdk-control-server-test.cpp" $(pkg-config --libs gio-2.0 json-glib-1.0) -o /tmp/sdk-control-server-test
timeout 20 /tmp/sdk-control-server-test
ffmpeg -v error -f lavfi -i color=c=blue:size=320x240 -frames:v 1 -threads 1 /tmp/image-test.png
g++ -std=c++11 -pthread -I/app/demo -I/app/demo/include/h \
    "$test_root/image-source-test.cpp" /app/demo/ZoomSDKVideoSource.cpp -o /tmp/image-source-test
timeout 20 /tmp/image-source-test
