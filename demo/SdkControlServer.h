#pragma once
#include <gio/gio.h>
#include <gio/gunixsocketaddress.h>
#include <json-glib/json-glib.h>
#include <functional>
#include <chrono>
#include <poll.h>
#include <string>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

// One bounded JSON line per connection. Handler runs on the SDK GLib main loop.
class SdkControlServer {
public:
    using Handler = std::function<JsonObject*(JsonObject*)>;
    SdkControlServer(std::string path, Handler handler) : path_(std::move(path)), handler_(std::move(handler)) {}
    ~SdkControlServer() {
        if (service_) { g_socket_service_stop(service_); g_socket_listener_close(G_SOCKET_LISTENER(service_)); g_object_unref(service_); }
        if (bound_) unlink(path_.c_str());
    }
    bool Start() {
        struct stat info;
        if (lstat(path_.c_str(), &info) == 0) {
            if (!S_ISSOCK(info.st_mode) || info.st_uid != getuid()) return false;
            // Never replace a socket that still has a live listener.
            int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
            auto address = g_unix_socket_address_new(path_.c_str());
            sockaddr_storage native{};
            g_socket_address_to_native(address, &native, sizeof(native), nullptr);
            const int connected = connect(fd, reinterpret_cast<sockaddr*>(&native), g_socket_address_get_native_size(address));
            g_object_unref(address); close(fd);
            if (connected == 0 || unlink(path_.c_str()) != 0) return false;
        }
        service_ = g_socket_service_new();
        auto address = g_unix_socket_address_new(path_.c_str());
        const auto mask = umask(0077);
        const bool success = g_socket_listener_add_address(G_SOCKET_LISTENER(service_), address,
            G_SOCKET_TYPE_STREAM, G_SOCKET_PROTOCOL_DEFAULT, nullptr, nullptr, nullptr);
        umask(mask); g_object_unref(address);
        if (!success) return false;
        bound_ = true;
        if (chmod(path_.c_str(), 0600) != 0) return false;
        g_signal_connect(service_, "incoming", G_CALLBACK(Incoming), this);
        g_socket_service_start(service_);
        return true;
    }
private:
    static gboolean Incoming(GSocketService*, GSocketConnection* connection, GObject*, gpointer data) {
        auto self = static_cast<SdkControlServer*>(data);
        const int fd = g_socket_get_fd(g_socket_connection_get_socket(connection));
        timeval timeout{1, 0};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        std::string line;
        char buffer[1024];
        bool complete = false;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
        while (line.size() <= 8192) {
            const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now()).count();
            if (remaining <= 0) break;
            pollfd ready{fd, POLLIN, 0};
            if (poll(&ready, 1, static_cast<int>(remaining)) <= 0) break;
            const auto count = recv(fd, buffer, sizeof(buffer), 0);
            if (count <= 0) break;
            line.append(buffer, count);
            if (line.find('\n') != std::string::npos) { complete = true; break; }
        }
        auto parser = json_parser_new();
        JsonObject* response = nullptr;
        if (complete && line.size() <= 8192) {
            line.resize(line.find('\n'));
            if (json_parser_load_from_data(parser, line.c_str(), line.size(), nullptr)) {
                auto root = json_parser_get_root(parser);
                if (JSON_NODE_HOLDS_OBJECT(root)) response = self->handler_(json_node_get_object(root));
            }
        }
        if (!response) {
            response = json_object_new();
            json_object_set_boolean_member(response, "ok", false);
            json_object_set_string_member(response, "error", "INVALID_REQUEST");
        }
        auto node = json_node_new(JSON_NODE_OBJECT);
        json_node_take_object(node, response);
        auto generator = json_generator_new();
        json_generator_set_root(generator, node);
        auto encoded = json_generator_to_data(generator, nullptr);
        const std::string output = std::string(encoded) + "\n";
        size_t offset = 0;
        while (offset < output.size()) {
            pollfd ready{fd, POLLOUT, 0};
            if (poll(&ready, 1, 1000) <= 0) break;
            const auto count = send(fd, output.data() + offset, output.size() - offset, MSG_NOSIGNAL);
            if (count <= 0) break;
            offset += count;
        }
        g_free(encoded); json_node_free(node); g_object_unref(generator); g_object_unref(parser);
        g_io_stream_close(G_IO_STREAM(connection), nullptr, nullptr);
        return TRUE;
    }
    std::string path_;
    Handler handler_;
    GSocketService* service_ = nullptr;
    bool bound_ = false;
};
