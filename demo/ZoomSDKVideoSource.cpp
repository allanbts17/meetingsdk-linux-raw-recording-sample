#include "ZoomSDKVideoSource.h"
#include <algorithm>
#include <chrono>
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

ZoomSDKVideoSource::ZoomSDKVideoSource(std::string source, std::shared_ptr<PlaybackClock> clock, bool image, double duration)
    : source_(std::move(source)), clock_(clock ? clock : std::make_shared<PlaybackClock>(true, false)), image_(image), duration_(duration) {}
ZoomSDKVideoSource::~ZoomSDKVideoSource() { Stop(); }
void ZoomSDKVideoSource::SetMedia(std::string source, std::shared_ptr<PlaybackClock> clock, bool image, double duration) {
    Stop();
    source_ = std::move(source); clock_ = std::move(clock);
    position_ = 0; completed_ = false; failed_ = false; accepted_ = 0; image_ = image; duration_ = duration;
}
void ZoomSDKVideoSource::Stop() {
    stop_ = true;
    clock_->Wake();
    wake_.notify_all();
    if (worker_.joinable()) worker_.join();
}
void ZoomSDKVideoSource::ApplyCapability(const VideoSourceCapability& cap) {
    if (cap.width >= 2 && cap.height >= 2 && cap.width <= 4096 && cap.height <= 4096 && cap.width % 2 == 0 && cap.height % 2 == 0) {
        width_ = cap.width; height_ = cap.height;
    }
    if (cap.frame) fps_ = std::min(cap.frame, 30u);
}
void ZoomSDKVideoSource::onInitialize(IZoomSDKVideoSender* sender, IList<VideoSourceCapability>*, VideoSourceCapability& cap) {
    Stop(); sender_ = sender; initialized_ = sender != nullptr; ApplyCapability(cap);
    std::cout << "Virtual camera initialized." << std::endl;
}
void ZoomSDKVideoSource::onPropertyChange(IList<VideoSourceCapability>*, VideoSourceCapability cap) {
    const bool restart = !stop_.load();
    Stop(); ApplyCapability(cap);
    if (restart && !completed_) onStartSend();
}
void ZoomSDKVideoSource::onStartSend() {
    if (!stop_.load()) return;
    Stop();
    if (!sender_ || completed_ || clock_->IsHalted()) return;
    stop_ = false;
    worker_ = std::thread(&ZoomSDKVideoSource::Play, this);
}
void ZoomSDKVideoSource::onStopSend() {
    std::cout << "Video source stop callback." << std::endl;
    if (!completed_) clock_->Pause("video_unavailable");
    Stop();
}
void ZoomSDKVideoSource::onUninitialized() {
    onStopSend(); sender_ = nullptr; initialized_ = false;
    std::cout << "Video source uninitialized callback." << std::endl;
}

void ZoomSDKVideoSource::Play() {
    int descriptors[2];
    if (pipe2(descriptors, O_CLOEXEC) != 0) { failed_ = true; stop_ = true; std::cerr << "Cannot create decoder pipe." << std::endl; return; }
    const std::string filter = "scale=" + std::to_string(width_) + ":" + std::to_string(height_) +
        ":force_original_aspect_ratio=decrease:force_divisible_by=2:out_range=tv,pad=" + std::to_string(width_) + ":" +
        std::to_string(height_) + ":(ow-iw)/2:(oh-ih)/2,setsar=1" + (image_ ? "" : ",fps=" + std::to_string(fps_));
    std::vector<std::string> args = {"ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
        "-i", source_, "-map", "0:v:0", "-an", "-vf", filter,
        "-filter_threads", "1", "-pix_fmt", "yuv420p", "-f", "rawvideo", "pipe:1"};
    // Still images have one frame: seeking, even to zero, can discard it for JPEG.
    // Decode once; the playback clock repeats the cached frame at negotiated FPS.
    if (image_) args.insert(args.end() - 1, {"-frames:v", "1"});
    else args.insert(args.begin() + 7, {"-ss", std::to_string(position_.load())});
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
    if (spawned) { close(descriptors[0]); failed_ = true; stop_ = true; std::cerr << "Cannot start FFmpeg." << std::endl; return; }
    std::vector<char> frame(width_ * height_ * 3 / 2);
    size_t filled = 0, sent = 0;
    unsigned int errors = 0;
    bool eof = false;
    bool imageLoaded = false, decoderReaped = false;
    int status = 0;
    const double initialPosition = position_;
    bool clockReady = false;
    std::cout << "Video playback started: " << width_ << "x" << height_ << " at " << fps_ << " fps." << std::endl;
    while (!stop_) {
        if (image_ && duration_ > 0 && initialPosition + static_cast<double>(sent) / fps_ >= duration_) {
            eof = true; filled = 0; break;
        }
        if (!imageLoaded) {
        pollfd readable = {descriptors[0], POLLIN, 0};
        const int ready = poll(&readable, 1, 100);
        if (ready < 0) { if (errno == EINTR) continue; break; }
        if (!ready) continue;
        const ssize_t count = read(descriptors[0], frame.data() + filled, frame.size() - filled);
        if (!count) { eof = true; break; }
        if (count < 0) { if (errno == EINTR) continue; break; }
        filled += static_cast<size_t>(count);
        if (filled < frame.size()) continue;
        if (image_) {
            close(descriptors[0]); descriptors[0] = -1;
            while (waitpid(decoder, &status, 0) < 0 && errno == EINTR) {}
            decoderReaped = true;
            if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) break;
            imageLoaded = true;
        }
        }
        if (!clockReady) {
            clockReady = clock_->ReadyAndWait(false, stop_);
            if (!clockReady) { std::cerr << "Video waiting for media readiness timed out or stopped." << std::endl; break; }
        }
        if (!clock_->Dispatch(initialPosition + static_cast<double>(sent) / fps_, stop_, [&](bool late) {
            position_ = initialPosition + static_cast<double>(sent + 1) / fps_;
            if (late) return;
            const SDKError result = sender_->sendVideoFrame(frame.data(), width_, height_, frame.size(), 0);
            if (result != SDKERR_SUCCESS) {
                if (++errors == 1) std::cerr << "Video frame send failed, SDK error: " << result << std::endl;
            } else {
                ++accepted_;
                errors = 0;
                if (!sent) std::cout << "First video frame accepted by SDK." << std::endl;
            }
        })) break;
        if (errors >= 30) break;
        ++sent;
        if (!imageLoaded) filled = 0;
    }
    if (descriptors[0] >= 0) close(descriptors[0]);
    if (!decoderReaped) {
        if (!eof) kill(decoder, SIGTERM);
        while (waitpid(decoder, &status, 0) < 0 && errno == EINTR) {}
    }
    if (eof && filled == 0 && WIFEXITED(status) && WEXITSTATUS(status) == 0) {
        completed_ = true;
        std::cout << "Video playback finished; no repeat. Frames: " << sent << std::endl;
    } else if (!stop_ && !clock_->IsHalted()) { failed_ = true; std::cerr << "Video decoding/sending ended before completion." << std::endl; }
    stop_ = true;
}
