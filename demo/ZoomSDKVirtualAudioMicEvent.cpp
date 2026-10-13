#include "ZoomSDKVirtualAudioMicEvent.h"
#include <algorithm>
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <iostream>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
extern char** environ;
using namespace ZOOMSDK;

ZoomSDKVirtualAudioMicEvent::ZoomSDKVirtualAudioMicEvent(std::string source, std::shared_ptr<PlaybackClock> clock, std::function<void()> prepareAudio)
    : source_(std::move(source)), clock_(clock ? clock : std::make_shared<PlaybackClock>(false, true)), prepareAudio_(std::move(prepareAudio)) {}
ZoomSDKVirtualAudioMicEvent::~ZoomSDKVirtualAudioMicEvent() { Stop(); }
void ZoomSDKVirtualAudioMicEvent::SetMedia(std::string source, std::shared_ptr<PlaybackClock> clock) {
    Stop();
    source_ = std::move(source); clock_ = std::move(clock);
    position_ = 0; completed_ = false;
}
void ZoomSDKVirtualAudioMicEvent::Stop() {
    stop_ = true; clock_->Wake(); wake_.notify_all();
    if (worker_.joinable()) worker_.join();
}
void ZoomSDKVirtualAudioMicEvent::onMicInitialize(IZoomSDKAudioRawDataSender* sender) {
    Stop(); sender_ = sender;
    std::cout << "Virtual microphone initialized." << std::endl;
}
void ZoomSDKVirtualAudioMicEvent::onMicStartSend() {
    if (!stop_.load()) return;
    Stop();
    if (!sender_ || completed_ || clock_->IsHalted()) return;
    if (prepareAudio_) prepareAudio_();
    stop_ = false; worker_ = std::thread(&ZoomSDKVirtualAudioMicEvent::Play, this);
}
void ZoomSDKVirtualAudioMicEvent::onMicStopSend() { Stop(); }
void ZoomSDKVirtualAudioMicEvent::onMicUninitialized() { Stop(); sender_ = nullptr; }

void ZoomSDKVirtualAudioMicEvent::Play() {
    int descriptors[2];
    if (pipe2(descriptors, O_CLOEXEC) != 0) { stop_ = true; std::cerr << "Cannot create audio decoder pipe." << std::endl; return; }
    std::vector<std::string> args = {"ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
        "-ss", std::to_string(position_), "-i", source_, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "48000",
        "-acodec", "pcm_s16le", "-f", "s16le", "pipe:1"};
    std::vector<char*> argv;
    for (auto& arg : args) argv.push_back(&arg[0]);
    argv.push_back(nullptr);
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, descriptors[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions, descriptors[0]);
    posix_spawn_file_actions_addclose(&actions, descriptors[1]);
    pid_t decoder;
    const int spawned = posix_spawnp(&decoder, "ffmpeg", &actions, nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    close(descriptors[1]);
    if (spawned) { close(descriptors[0]); stop_ = true; std::cerr << "Cannot start audio FFmpeg." << std::endl; return; }
    // 10 ms of signed 16-bit mono PCM at 48000 Hz; no WAV header.
    std::vector<char> block(960);
    size_t filled = 0, blocks = 0;
    unsigned int errors = 0;
    bool eof = false, clockReady = false;
    const double initialPosition = position_;
    std::cout << "Audio playback started: PCM s16le mono 48000 Hz, 10 ms blocks." << std::endl;
    while (!stop_) {
        pollfd readable = {descriptors[0], POLLIN, 0};
        const int ready = poll(&readable, 1, 100);
        if (ready < 0) { if (errno == EINTR) continue; break; }
        if (!ready) continue;
        const ssize_t count = read(descriptors[0], block.data() + filled, block.size() - filled);
        if (count < 0) { if (errno == EINTR) continue; break; }
        if (!count) {
            eof = true;
            if (!filled) break;
            if (filled % 2) { std::cerr << "Incomplete PCM sample." << std::endl; break; }
            // Zero-pad the last partial block, preserving all remaining samples.
            std::fill(block.begin() + filled, block.end(), 0);
            filled = block.size();
        } else filled += static_cast<size_t>(count);
        if (filled < block.size()) continue;
        if (!clockReady) {
            clockReady = clock_->ReadyAndWait(true, stop_);
            if (!clockReady) { std::cerr << "Audio waiting for media readiness timed out or stopped." << std::endl; break; }
        }
        if (!clock_->Dispatch(initialPosition + blocks * 0.01, stop_, [&](bool late) {
            if (late) return;
            const SDKError result = sender_->send(block.data(), block.size(), 48000, ZoomSDKAudioChannel_Mono);
            if (result != SDKERR_SUCCESS) {
                if (++errors == 1) std::cerr << "Audio block send failed, SDK error: " << result << std::endl;
            } else {
                errors = 0;
                if (!blocks) std::cout << "First audio block accepted by SDK." << std::endl;
            }
        })) break;
        if (errors >= 100) break;
        ++blocks; position_ = initialPosition + blocks * 0.01; filled = 0;
        if (eof) break;
    }
    if (!eof) kill(decoder, SIGTERM);
    close(descriptors[0]);
    int status = 0;
    while (waitpid(decoder, &status, 0) < 0 && errno == EINTR) {}
    if (eof && !filled && WIFEXITED(status) && WEXITSTATUS(status) == 0) {
        completed_ = true;
        std::cout << "Audio playback finished; no repeat. Blocks: " << blocks << std::endl;
    } else if (!stop_ && !clock_->IsHalted()) std::cerr << "Audio decoding/sending ended before completion." << std::endl;
    stop_ = true;
}
