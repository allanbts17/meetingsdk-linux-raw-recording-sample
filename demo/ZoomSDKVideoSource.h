#pragma once
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <memory>
#include "PlaybackClock.h"
#include <string>
#include <thread>
#include "rawdata/rawdata_video_source_helper_interface.h"

class ZoomSDKVideoSource : public ZOOMSDK::IZoomSDKVideoSource {
public:
    explicit ZoomSDKVideoSource(std::string source, std::shared_ptr<PlaybackClock> clock = nullptr, bool image = false, double duration = 0);
    ~ZoomSDKVideoSource() override;
    void Stop();
    void SetMedia(std::string source, std::shared_ptr<PlaybackClock> clock, bool image = false, double duration = 0);
    double Position() const { return position_.load(); }
    bool HasFailed() const { return failed_.load(); }
    unsigned long AcceptedFrames() const { return accepted_.load(); }
    bool IsCompleted() const { return completed_.load(); }
    bool IsSending() const { return !stop_.load(); }
    void onInitialize(ZOOMSDK::IZoomSDKVideoSender*, ZOOMSDK::IList<ZOOMSDK::VideoSourceCapability>*, ZOOMSDK::VideoSourceCapability&) override;
    void onPropertyChange(ZOOMSDK::IList<ZOOMSDK::VideoSourceCapability>*, ZOOMSDK::VideoSourceCapability) override;
    void onStartSend() override;
    void onStopSend() override;
    void onUninitialized() override;
private:
    void ApplyCapability(const ZOOMSDK::VideoSourceCapability&);
    void Play();
    ZOOMSDK::IZoomSDKVideoSender* sender_ = nullptr;
    std::string source_;
    std::shared_ptr<PlaybackClock> clock_;
    std::thread worker_;
    std::atomic<bool> stop_{true};
    std::mutex waitMutex_;
    std::condition_variable wake_;
    unsigned int width_ = 640, height_ = 480, fps_ = 30;
    std::atomic<double> position_{0};
    bool image_ = false;
    double duration_ = 0;
    std::atomic<bool> completed_{false};
    std::atomic<bool> failed_{false};
    std::atomic<unsigned long> accepted_{0};
};
