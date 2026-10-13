#include "SdkControlServer.h"
#include <cassert>
#include <thread>
#include <sys/un.h>

std::string Exchange(const std::string& message, bool fragmented = false) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un address{}; address.sun_family = AF_UNIX;
    strcpy(address.sun_path, "/tmp/sdk-control-test.sock");
    assert(connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0);
    if (fragmented) {
        assert(send(fd, message.data(), 2, MSG_NOSIGNAL) == 2);
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
        assert(send(fd, message.data() + 2, message.size() - 2, MSG_NOSIGNAL) == static_cast<ssize_t>(message.size() - 2));
    } else send(fd, message.data(), message.size(), MSG_NOSIGNAL);
    char buffer[1024]; const auto size = recv(fd, buffer, sizeof(buffer), 0);
    close(fd); assert(size > 0); return std::string(buffer, size);
}

int main() {
    int handled = 0;
    auto loop = g_main_loop_new(nullptr, FALSE);
    SdkControlServer server("/tmp/sdk-control-test.sock", [&](JsonObject*) {
        ++handled; auto result = json_object_new(); json_object_set_boolean_member(result, "ok", true); return result;
    });
    assert(server.Start());
    struct stat info; assert(stat("/tmp/sdk-control-test.sock", &info) == 0 && (info.st_mode & 0777) == 0600);
    SdkControlServer duplicate("/tmp/sdk-control-test.sock", [](JsonObject*) { return json_object_new(); });
    assert(!duplicate.Start()); // A live listener must not be replaced.
    std::thread client([&] {
        assert(Exchange("{\"command\":\"status\"}\n", true).find("true") != std::string::npos);
        assert(Exchange("[]\n").find("INVALID_REQUEST") != std::string::npos);
        assert(Exchange("broken\n").find("INVALID_REQUEST") != std::string::npos);
        assert(Exchange(std::string(8500, 'x') + "\n").find("INVALID_REQUEST") != std::string::npos);
        g_main_loop_quit(loop);
    });
    g_main_loop_run(loop); client.join(); assert(handled == 1); g_main_loop_unref(loop);
}
