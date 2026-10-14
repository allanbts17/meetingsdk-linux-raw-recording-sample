#include "ZoomSDKVideoSource.h"
#include "MediaValidation.h"
#include <cassert>
#include <chrono>
#include <thread>
#include <vector>
#include <iostream>
using namespace ZOOMSDK;
class ImageSender : public IZoomSDKVideoSender {
public:
    std::atomic<int> count{0};
    std::vector<char> first;
    SDKError sendVideoFrame(char* bytes, int w, int h, int size, int) override {
        assert(w == 320 && h == 240 && size == 115200);
        std::vector<char> frame(bytes, bytes + size);
        if (!count) first = frame;
        else assert(frame == first);
        ++count; return SDKERR_SUCCESS;
    }
};
int main() {
    std::string error;
    assert(ValidateMedia("/tmp/image-test.png", true, false, error, true));
    assert(!ValidateMedia("/tmp/video-only.mp4", true, false, error, true));
    ImageSender sender;
    VideoSourceCapability cap(320, 240, 30);
    auto clock = std::make_shared<PlaybackClock>(true, false);
    ZoomSDKVideoSource image("/tmp/image-test.png", clock, true, 1);
    image.onInitialize(&sender, nullptr, cap); image.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(550));
    clock->Pause(); const auto count = sender.count.load(); const auto position = image.Position();
    assert(count > 0 && count < 30);
    std::this_thread::sleep_for(std::chrono::milliseconds(800));
    assert(sender.count == count && image.Position() == position && !image.IsCompleted());
    clock->Resume();
    std::this_thread::sleep_for(std::chrono::milliseconds(1000)); image.Stop();
    assert(image.IsCompleted() && sender.count == 30 && image.AcceptedFrames() == 30 && image.Position() == 1 && !image.HasFailed());
    sender.count = 0;
    auto indefinite = std::make_shared<PlaybackClock>(true, false);
    image.SetMedia("/tmp/image-test.png", indefinite, true);
    image.onStartSend(); std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    assert(!image.IsCompleted() && sender.count > 30);
    indefinite->Halt(); image.Stop();
    const auto stopped = sender.count.load();
    std::this_thread::sleep_for(std::chrono::milliseconds(100)); assert(sender.count == stopped);
    // JPEG at the SDK's 25 FPS must emit its only decoded frame and repeat it.
    ImageSender jpegSender;
    ZoomSDKVideoSource jpeg("/tmp/image-test.jpg", std::make_shared<PlaybackClock>(true, false), true, 1);
    VideoSourceCapability jpegCap(320, 240, 25);
    jpeg.onInitialize(&jpegSender, nullptr, jpegCap);
    jpeg.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(1500)); jpeg.Stop();
    assert(jpeg.IsCompleted() && !jpeg.HasFailed() && jpeg.AcceptedFrames() == 25 && jpegSender.count == 25);
    auto missing = std::make_shared<PlaybackClock>(true, false);
    image.SetMedia("/tmp/does-not-exist.png", missing, true, 1); image.onStartSend();
    std::this_thread::sleep_for(std::chrono::milliseconds(500)); image.Stop();
    assert(image.HasFailed() && !image.IsCompleted() && image.AcceptedFrames() == 0);
    std::cout << "Image tests passed: identical cached frames, paused timer, duration, indefinite display, stop and decode failure." << std::endl;
}
