#include "ZoomSDKVideoSource.h"
#include "ZoomSDKVirtualAudioMicEvent.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <iostream>
#include <thread>
using namespace ZOOMSDK;
class Video : public IZoomSDKVideoSender {
public:
    std::atomic<int> count{0};
    SDKError sendVideoFrame(char*, int w, int h, int size, int) override {
        assert(w == 320 && h == 240 && size == 115200); ++count; return SDKERR_SUCCESS;
    }
};
class Audio : public IZoomSDKAudioRawDataSender {
public:
    std::atomic<int> count{0};
    SDKError send(char*, unsigned int size, int rate, ZoomSDKAudioChannel channel) override {
        assert(size == 960 && rate == 48000 && channel == ZoomSDKAudioChannel_Mono); ++count; return SDKERR_SUCCESS;
    }
};
int main() {
    auto clock = std::make_shared<PlaybackClock>(true, true);
    Video senderV; Audio senderA;
    VideoSourceCapability cap(320, 240, 30);
    ZoomSDKVideoSource video("/tmp/av-test.mkv", clock);
    ZoomSDKVirtualAudioMicEvent audio("/tmp/av-test.mkv", clock);
    video.onInitialize(&senderV, nullptr, cap); audio.onMicInitialize(&senderA);
    video.onStartSend(); audio.onMicStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(450));
    assert(senderV.count > 0 && senderA.count > 0);
    clock->Pause(); clock->Pause();
    const int frames = senderV.count, blocks = senderA.count;
    std::this_thread::sleep_for(std::chrono::milliseconds(350));
    assert(clock->State() == "paused" && senderV.count == frames && senderA.count == blocks);
    clock->Resume(); clock->Resume();
    std::this_thread::sleep_for(std::chrono::milliseconds(1100));
    video.Stop(); audio.Stop();
    assert(video.IsCompleted() && audio.IsCompleted());
    assert(senderV.count == 30 && senderA.count == 100); // No media lost during the pause.

    auto halted = std::make_shared<PlaybackClock>(true, true);
    ZoomSDKVideoSource stoppedV("/tmp/av-test.mkv", halted);
    ZoomSDKVirtualAudioMicEvent stoppedA("/tmp/av-test.mkv", halted);
    stoppedV.onInitialize(&senderV, nullptr, cap); stoppedA.onMicInitialize(&senderA);
    stoppedV.onStartSend(); stoppedA.onMicStartSend();
    stoppedV.onStartSend(); stoppedA.onMicStartSend(); // Duplicate callbacks must not restart decoders.
    std::this_thread::sleep_for(std::chrono::milliseconds(450));
    halted->Pause(); halted->Halt();
    const auto start = std::chrono::steady_clock::now();
    stoppedV.Stop(); stoppedA.Stop();
    assert(std::chrono::steady_clock::now() - start < std::chrono::seconds(2));
    const int finalV = senderV.count, finalA = senderA.count;
    halted->Resume(); stoppedV.onStartSend(); stoppedA.onMicStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(150));
    assert(halted->State() == "stopped" && senderV.count == finalV && senderA.count == finalA);
    // Reuse the same registered source instances: no SDK reinitialization/rejoin.
    auto fresh = std::make_shared<PlaybackClock>(true, true);
    stoppedV.SetMedia("/tmp/av-test.mkv", fresh);
    stoppedA.SetMedia("/tmp/av-test.mkv", fresh);
    stoppedV.onStartSend(); stoppedA.onMicStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    stoppedV.Stop(); stoppedA.Stop();
    assert(stoppedV.IsCompleted() && stoppedA.IsCompleted());
    assert(senderV.count == finalV + 30 && senderA.count == finalA + 100);
    auto videoOnly = std::make_shared<PlaybackClock>(true, false);
    stoppedV.SetMedia("/tmp/video-only.mp4", videoOnly);
    const int beforeVideoOnly = senderV.count;
    stoppedV.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    stoppedV.Stop();
    assert(stoppedV.IsCompleted() && senderV.count == beforeVideoOnly + 30 && senderA.count == finalA + 100);
    auto audioOnly = std::make_shared<PlaybackClock>(false, true);
    stoppedA.SetMedia("/tmp/av-test.mkv", audioOnly);
    stoppedA.onMicStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    stoppedA.Stop();
    assert(stoppedA.IsCompleted() && senderA.count == finalA + 200);
    std::cout << "Controls passed: pause freezes both tracks, resume preserves all media, stop during pause cannot restart." << std::endl;
}
