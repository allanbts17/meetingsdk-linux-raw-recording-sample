#pragma once
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <functional>
#include <string>

// Both decoded tracks must be ready before the first media deadline is set.
class PlaybackClock {
public:
    PlaybackClock(bool video, bool audio) : videoReady_(!video), audioReady_(!audio) {}
    bool ReadyAndWait(bool audio, const std::atomic<bool>& stopped) {
        std::unique_lock<std::mutex> lock(mutex_);
        (audio ? audioReady_ : videoReady_) = true;
        if (!started_ && videoReady_ && audioReady_) {
            epoch_ = (paused_ ? pausedAt_ : std::chrono::steady_clock::now()) + std::chrono::milliseconds(200);
            started_ = true;
            wake_.notify_all();
        }
        const auto timeout = std::chrono::steady_clock::now() + std::chrono::seconds(15);
        while (!started_ && !stopped && !halted_ && std::chrono::steady_clock::now() < timeout)
            wake_.wait_for(lock, std::chrono::milliseconds(100));
        return started_ && !stopped && !halted_;
    }
    std::chrono::steady_clock::time_point Deadline(double seconds) {
        std::lock_guard<std::mutex> lock(mutex_);
        return epoch_ + std::chrono::microseconds(static_cast<long long>(seconds * 1000000));
    }
    void Wake() { wake_.notify_all(); }
    void Pause() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (paused_ || halted_) return;
        paused_ = true; pausedAt_ = std::chrono::steady_clock::now(); wake_.notify_all();
    }
    void Resume() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!paused_ || halted_) return;
        if (started_) epoch_ += std::chrono::steady_clock::now() - pausedAt_;
        paused_ = false; wake_.notify_all();
    }
    void Halt() {
        std::lock_guard<std::mutex> lock(mutex_);
        halted_ = true; paused_ = false; wake_.notify_all();
    }
    bool IsHalted() { std::lock_guard<std::mutex> lock(mutex_); return halted_; }
    std::string State() {
        std::lock_guard<std::mutex> lock(mutex_);
        return halted_ ? "stopped" : paused_ ? "paused" : started_ ? "playing" : "waiting";
    }
    // Holding the clock lock through dispatch guarantees no new sends after Pause/Halt returns.
    bool Dispatch(double seconds, const std::atomic<bool>& stopped, const std::function<void(bool)>& send) {
        std::unique_lock<std::mutex> lock(mutex_);
        while (!stopped && !halted_) {
            if (paused_) { wake_.wait_for(lock, std::chrono::milliseconds(100)); continue; }
            const auto due = epoch_ + std::chrono::microseconds(static_cast<long long>(seconds * 1000000));
            if (std::chrono::steady_clock::now() < due) { wake_.wait_until(lock, due); continue; }
            send(std::chrono::steady_clock::now() > due + std::chrono::milliseconds(150));
            return true;
        }
        return false;
    }
private:
    std::mutex mutex_;
    std::condition_variable wake_;
    bool videoReady_, audioReady_, started_ = false;
    bool paused_ = false, halted_ = false;
    std::chrono::steady_clock::time_point pausedAt_;
    std::chrono::steady_clock::time_point epoch_;
};
