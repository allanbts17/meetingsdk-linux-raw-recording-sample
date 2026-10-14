#include "ZoomSDKVideoSource.h"
#include "ZoomSDKVirtualAudioMicEvent.h"
#include <cassert>
#include <chrono>
#include <thread>
#include <iostream>
using namespace ZOOMSDK;
class RejectVideo : public IZoomSDKVideoSender {
    SDKError sendVideoFrame(char*, int, int, int, int) override { return SDKERR_WRONG_USAGE; }
};
class RejectAudio : public IZoomSDKAudioRawDataSender {
    SDKError send(char*, unsigned int, int, ZoomSDKAudioChannel) override { return SDKERR_WRONG_USAGE; }
};
int main() {
    RejectVideo vs; RejectAudio as;
    ZoomSDKVideoSource video("/tmp/av-failure-test.mkv");
    ZoomSDKVirtualAudioMicEvent audio("/tmp/av-failure-test.mkv");
    VideoSourceCapability cap(320, 240, 30);
    video.onInitialize(&vs, nullptr, cap);
    audio.onMicInitialize(&as);
    video.onStartSend(); audio.onMicStartSend();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while ((!video.HasFailed() || !audio.HasFailed()) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    video.Stop(); audio.Stop();
    assert(video.HasFailed() && audio.HasFailed());
    assert(video.AcceptedFrames() == 0 && audio.AcceptedBlocks() == 0);
    assert(!video.IsCompleted() && !audio.IsCompleted());
    std::cout << "Rejected audio/video sends are failures, never successful EOF." << std::endl;
}
