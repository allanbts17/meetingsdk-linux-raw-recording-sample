#pragma once
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <string>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
#include <algorithm>
#include <cctype>
extern char** environ;

// Probe a regular local file without a shell or network protocols.
inline bool ValidateMedia(const std::string& source, bool video, bool audio, std::string& error, bool image = false) {
    struct stat info;
    if (stat(source.c_str(), &info) != 0 || !S_ISREG(info.st_mode)) {
        error = "Media file is missing or is not a regular file. Check the read-only video mount.";
        return false;
    }
    if (image) {
        auto suffix = source.substr(source.find_last_of('.') == std::string::npos ? source.size() : source.find_last_of('.'));
        std::transform(suffix.begin(), suffix.end(), suffix.begin(), [](unsigned char c) { return std::tolower(c); });
        if ((suffix != ".png" && suffix != ".jpg" && suffix != ".jpeg") || info.st_size > 10 * 1024 * 1024) {
            error = "Image must be PNG/JPEG and at most 10 MiB."; return false;
        }
    }
    int descriptors[2];
    if (pipe2(descriptors, O_CLOEXEC) != 0) { error = "Cannot create media probe pipe."; return false; }
    std::vector<std::string> args = {"ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_entries", image ? "stream=codec_name,codec_type" : "stream=codec_type", "-of", "csv=p=0", source};
    std::vector<char*> argv;
    for (auto& arg : args) argv.push_back(&arg[0]);
    argv.push_back(nullptr);
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, descriptors[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions, descriptors[0]);
    posix_spawn_file_actions_addclose(&actions, descriptors[1]);
    pid_t probe;
    const int spawned = posix_spawnp(&probe, "ffprobe", &actions, nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    close(descriptors[1]);
    if (spawned) { close(descriptors[0]); error = "Cannot run ffprobe; check the Docker image."; return false; }
    std::string streams;
    bool ended = false;
    // Bound probe time to avoid waiting forever on corrupt files.
    for (int attempts = 0; attempts < 100 && !ended; ++attempts) {
        pollfd readable = {descriptors[0], POLLIN, 0};
        const int ready = poll(&readable, 1, 100);
        if (ready < 0) { if (errno == EINTR) continue; break; }
        if (!ready) continue;
        char buffer[256];
        const auto count = read(descriptors[0], buffer, sizeof(buffer));
        if (count == 0) ended = true;
        else if (count > 0) { streams.append(buffer, count); if (streams.size() > 4096) break; }
        else if (errno != EINTR) break;
    }
    if (!ended) kill(probe, SIGKILL);
    close(descriptors[0]);
    int status = 0;
    while (waitpid(probe, &status, 0) < 0 && errno == EINTR) {}
    if (!ended || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        error = "Invalid/unsupported media file or probe timed out."; return false;
    }
    if ((video && streams.find("video") == std::string::npos) || (audio && streams.find("audio") == std::string::npos)) {
        error = "Media file lacks an enabled audio/video track. Disable that track or choose another file."; return false;
    }
    if (image && streams.compare(0, 4, "png,") != 0 && streams.compare(0, 6, "mjpeg,") != 0) {
        error = "Image codec must be PNG or JPEG."; return false;
    }
    return true;
}
