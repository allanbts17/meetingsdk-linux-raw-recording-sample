#include "ZoomSDKVideoSource.h"
#include "ZoomSDKVirtualAudioMicEvent.h"
#include <cassert>
#include <chrono>
#include <thread>
#include <atomic>
#include <iostream>
using namespace ZOOMSDK;
using Clock = std::chrono::steady_clock;
class VideoSender : public IZoomSDKVideoSender {
public:
    std::atomic<int> frames{0};
    Clock::time_point first;
    SDKError sendVideoFrame(char* data, int width, int height, int size, int rotation) override {
        assert(data && width == 320 && height == 240 && size == 115200 && rotation == 0);
        if (!frames++) first = Clock::now();
        return SDKERR_SUCCESS;
    }
};
class AudioSender : public IZoomSDKAudioRawDataSender {
public:
    std::atomic<int> blocks{0};
    Clock::time_point first;
    bool nonzero = false;
    SDKError send(char* data, unsigned int size, int rate, ZoomSDKAudioChannel channel) override {
        assert(data && size == 960 && rate == 48000 && channel == ZoomSDKAudioChannel_Mono);
        for (unsigned int i = 0; i < size; ++i) nonzero = nonzero || data[i] != 0;
        if (!blocks++) first = Clock::now();
        return SDKERR_SUCCESS;
    }
};
int main() {
    auto clock = std::make_shared<PlaybackClock>(true, true);
    VideoSender videoSender;
    AudioSender audioSender;
    VideoSourceCapability cap(320, 240, 30);
    ZoomSDKVideoSource video("/tmp/av-test.mkv", clock);
    bool audioPrepared = false;
    ZoomSDKVirtualAudioMicEvent audio("/tmp/av-test.mkv", clock, [&] { audioPrepared = true; });
    video.onInitialize(&videoSender, nullptr, cap);
    audio.onMicInitialize(&audioSender);
    video.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    assert(videoSender.frames == 0); // Video waits for the audio track.
    audio.onMicStartSend();
    assert(audioPrepared);
    std::this_thread::sleep_for(std::chrono::milliseconds(1700));
    video.Stop(); audio.Stop();
    assert(videoSender.frames == 30 && audioSender.blocks == 100 && audioSender.nonzero);
    const auto skew = std::chrono::duration_cast<std::chrono::milliseconds>(videoSender.first - audioSender.first).count();
    assert(skew > -40 && skew < 40);
    video.onStartSend(); audio.onMicStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    video.Stop(); audio.Stop();
    assert(videoSender.frames == 30 && audioSender.blocks == 100);

    auto activeClock = std::make_shared<PlaybackClock>(true, true);
    ZoomSDKVideoSource activeVideo("/tmp/av-test.mkv", activeClock);
    ZoomSDKVirtualAudioMicEvent activeAudio("/tmp/av-test.mkv", activeClock);
    activeVideo.onInitialize(&videoSender, nullptr, cap);
    activeAudio.onMicInitialize(&audioSender);
    activeVideo.onStartSend(); activeAudio.onMicStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    assert(videoSender.frames > 30 && audioSender.blocks > 100);
    const auto activeStopStart = Clock::now();
    activeVideo.Stop(); activeAudio.Stop();
    assert(Clock::now() - activeStopStart < std::chrono::seconds(2));
    const int videoCount = videoSender.frames, audioCount = audioSender.blocks;
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    assert(videoSender.frames == videoCount && audioSender.blocks == audioCount);

    ZoomSDKVirtualAudioMicEvent cancelled("/tmp/av-test.mkv");
    cancelled.onMicInitialize(&audioSender);
    cancelled.onMicStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    const auto start = Clock::now();
    cancelled.Stop();
    assert(Clock::now() - start < std::chrono::seconds(1));
    const int count = audioSender.blocks;
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    assert(audioSender.blocks == count);
    std::cout << "AV tests passed: 30 frames, 100 PCM blocks, readiness barrier, start skew " << skew << " ms, no repeat, cancellation." << std::endl;
}
