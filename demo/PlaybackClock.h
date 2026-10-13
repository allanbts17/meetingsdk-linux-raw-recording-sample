#pragma once
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>

// Both decoded tracks must be ready before the first media deadline is set.
class PlaybackClock {
public:
    PlaybackClock(bool video, bool audio) : videoReady_(!video), audioReady_(!audio) {}
    bool ReadyAndWait(bool audio, const std::atomic<bool>& stopped) {
        std::unique_lock<std::mutex> lock(mutex_);
        (audio ? audioReady_ : videoReady_) = true;
        if (!started_ && videoReady_ && audioReady_) {
            epoch_ = std::chrono::steady_clock::now() + std::chrono::milliseconds(200);
            started_ = true;
            wake_.notify_all();
        }
        const auto timeout = std::chrono::steady_clock::now() + std::chrono::seconds(15);
        while (!started_ && !stopped && std::chrono::steady_clock::now() < timeout)
            wake_.wait_for(lock, std::chrono::milliseconds(100));
        return started_ && !stopped;
    }
    std::chrono::steady_clock::time_point Deadline(double seconds) {
        std::lock_guard<std::mutex> lock(mutex_);
        return epoch_ + std::chrono::microseconds(static_cast<long long>(seconds * 1000000));
    }
    void Wake() { wake_.notify_all(); }
private:
    std::mutex mutex_;
    std::condition_variable wake_;
    bool videoReady_, audioReady_, started_ = false;
    std::chrono::steady_clock::time_point epoch_;
};
