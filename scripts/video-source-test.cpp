#include "ZoomSDKVideoSource.h"
#include <cassert>
#include <chrono>
#include <thread>
#include <atomic>
#include <iostream>
using namespace ZOOMSDK;

class Sender : public IZoomSDKVideoSender {
public:
    std::atomic<int> frames{0};
    SDKError sendVideoFrame(char* data, int width, int height, int length, int rotation) override {
        assert(data && width == 320 && height == 240 && length == width * height * 3 / 2 && rotation == 0);
        ++frames;
        return SDKERR_SUCCESS;
    }
};
int main() {
    Sender sender;
    VideoSourceCapability cap(320, 240, 30);
    ZoomSDKVideoSource source("/tmp/video-test.mp4");
    source.onInitialize(&sender, nullptr, cap);
    source.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    source.onStopSend();
    assert(sender.frames == 30);
    source.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    source.onStopSend();
    assert(sender.frames == 30);
    source.onUninitialized();

    ZoomSDKVideoSource stopped("/tmp/video-test.mp4");
    stopped.onInitialize(&sender, nullptr, cap);
    stopped.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    const auto start = std::chrono::steady_clock::now();
    stopped.Stop();
    assert(std::chrono::steady_clock::now() - start < std::chrono::seconds(1));
    const int frames = sender.frames;
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    assert(sender.frames == frames);
    std::cout << "Video source tests passed: frame size, EOF, no repeat and cancellation." << std::endl;
}
