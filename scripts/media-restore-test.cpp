#include "MediaRestorePolicy.h"
#include "PlaybackClock.h"
#include <cassert>
#include <iostream>
int main() {
    MediaRestorePolicy retry;
    assert(!retry.ShouldAttempt(false, false, true, 0));
    assert(!retry.ShouldAttempt(true, true, true, 0));
    assert(!retry.ShouldAttempt(true, false, false, 0));
    assert(retry.ShouldAttempt(true, false, true, 0));
    retry.Attempted(true, 0);
    assert(!retry.ShouldAttempt(true, false, true, 0.2));
    assert(retry.ShouldAttempt(true, false, true, 1));
    retry.Attempted(false, 1);
    assert(!retry.ShouldAttempt(true, false, true, 3.9));
    assert(retry.ShouldAttempt(true, false, true, 4));
    assert(!retry.ShouldAttempt(true, true, true, 4));
    assert(retry.ShouldAttempt(true, false, true, 4.2));
    PlaybackClock clock(true, true);
    clock.Pause(); clock.Pause("audio_muted"); clock.Pause("video_disabled");
    clock.RemoveReason("audio_muted"); clock.RemoveReason("video_disabled");
    assert(clock.State() == "paused" && clock.PauseReasons() == std::vector<std::string>{"user"});
    clock.Halt();
    assert(!retry.ShouldAttempt(false, false, true, 5));
    assert(clock.State() == "stopped" && !clock.Resume());
    std::cout << "Media restoration policy passed: immediate attempts, bounded retries, permissions, manual pause and stop." << std::endl;
}
