#pragma once
#include <atomic>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include "PlaybackClock.h"
#include "rawdata/rawdata_audio_helper_interface.h"

class ZoomSDKVirtualAudioMicEvent : public ZOOMSDK::IZoomSDKVirtualAudioMicEvent {
public:
    explicit ZoomSDKVirtualAudioMicEvent(std::string source, std::shared_ptr<PlaybackClock> clock = nullptr,
        std::function<void()> prepareAudio = {});
    ~ZoomSDKVirtualAudioMicEvent() override;
    void Stop();
    bool IsSending() const { return !stop_.load(); }
    void onMicInitialize(ZOOMSDK::IZoomSDKAudioRawDataSender*) override;
    void onMicStartSend() override;
    void onMicStopSend() override;
    void onMicUninitialized() override;
private:
    void Play();
    ZOOMSDK::IZoomSDKAudioRawDataSender* sender_ = nullptr;
    std::string source_;
    std::shared_ptr<PlaybackClock> clock_;
    std::function<void()> prepareAudio_;
    std::thread worker_;
    std::atomic<bool> stop_{true};
    std::mutex waitMutex_;
    std::condition_variable wake_;
    double position_ = 0;
    bool completed_ = false;
};
