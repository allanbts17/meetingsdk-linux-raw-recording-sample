#pragma once

// Main-loop policy: immediate first attempt, bounded retries, reset on recovery.
class MediaRestorePolicy {
public:
    bool ShouldAttempt(bool desired, bool available, bool allowed, double now) {
        if (!desired || available || !allowed) { Reset(); return false; }
        return now >= next_;
    }
    void Attempted(bool success, double now) { next_ = now + (success ? 1.0 : 3.0); }
    void Reset() { next_ = 0; }
private:
    double next_ = 0;
};
